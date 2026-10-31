# NEET Compass: NEET-UG guidance, college prediction and college intelligence

A NEET-UG platform for students and families. Every factual record (cutoffs, seats, fees, hostels, rules,
info pages) keeps its **source, academic year, collection date, last-verified date and verification status**.

- Predictions come from a **transparent historical-cutoff matcher**, not from an LLM.
- The AI assistant only explains data it fetches through backend tools.

For students it covers:

- **Colleges:** fees, hostels, cutoffs, and what is **around the campus**: transport, food, places to stay, health,
  daily needs, libraries and gyms, on a map with walking estimates.
- **Practice:** **timed NEET-format tests** (full mock, mini mock, subject, chapter and weak-chapter practice) on
  an OMR-style answer sheet, with section- and chapter-wise analysis.
- **Planning:** a **week-by-week study plan** shaped by the student's class (11, 12 or dropper) and a syllabus tracker.

> ⚠️ The catalog ships with **DEMO data only**: fictional colleges named "… (DEMO)" with synthetic cutoffs and
> fees, labelled everywhere. Demo records can never be marked verified. Load real data with
> [docs/DATA_LOADING.md](docs/DATA_LOADING.md).

| Doc | For |
|---|---|
| [docs/DATA_LOADING.md](docs/DATA_LOADING.md) | Loading and verifying real data: sources and terms, imports, eligibility rules, info pages |
| [docs/FREE_HOSTING.md](docs/FREE_HOSTING.md) | Hosting for free: Render (website + API) + Neon (database) + Cloudflare (domain), step by step |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Docker production stack, HTTPS, backups, monitoring, scheduled jobs |
| [docs/DPDP_READINESS.md](docs/DPDP_READINESS.md) | Briefing for the DPDP Act 2023 legal review (data inventory, safeguards, open questions) |

## Stack

| Layer | Choice |
|---|---|
| Website | Server-rendered by the same Python app: Jinja2 templates · HTMX · Tailwind CSS 4 (built with `pytailwindcss`, no Node) · small scripts only for the exam clock, voice and the map |
| Backend | FastAPI · SQLAlchemy 2 · Alembic · Pydantic 2 |
| Tests | pytest · Playwright for Python (`pytest-playwright`) |
| Database | SQLite for zero-setup dev; PostgreSQL in production |
| Shared rate limits | Redis (`REDIS_URL`); in-process fallback |
| Assistant | Text and voice. LLM through OpenRouter (`OPENROUTER_API_KEY`, default `anthropic/claude-haiku-5.5`) or Anthropic directly; deterministic tool-only fallback without a key |
| Search | BM25 keyword ranking; plus Voyage AI embeddings for semantic matching (`VOYAGE_API_KEY`) |
| OCR | Tesseract (in the Docker image) for scanned PDFs |
| Nearby places | OpenStreetMap via Overpass (`PLACES_PROVIDER=overpass`), with attribution |

```
backend/
  app/
    models.py            # 44 tables; Provenance mixin on every factual record
    services/
      predictor.py       # historical cutoff matching (no probabilities)
      ingestion.py       # ETL for cutoffs / seat matrix / fees + documents (OCR, embeddings)
      retrieval.py       # BM25 + semantic (reciprocal-rank fusion)
      exams.py           # NEET-format practice tests: paper building, autosave, server-side timer, scoring
      study_plan.py      # class-based weekly study plan
      places.py, ocr.py, embeddings.py, email.py, costs.py, normalize.py, catalog.py, compare.py, assistant.py
    routers/             # JSON API: auth (+ guardian consent), profile, mock-tests, colleges, counselling, assistant, admin
    web/                 # the website: routes_*.py call the same API functions; templates/ (Jinja2 + HTMX);
                         # static/ (built app.css, mascot, small scripts); styles/input.css + build_css.py
    seed.py              # reference data + DEMO data (--no-demo, --remove-demo)
    practice_seed.py     # NEET-UG syllabus chapters + original sample questions
    maintenance.py       # scheduled jobs (purge-unconsented)
  alembic/               # migrations
  start.py               # container start: migrate, seed, serve
  scripts/e2e_server.py  # throwaway copy of the site for browser tests
  tests/                 # pytest: API and website routes
  e2e/                   # browser tests (Playwright for Python)
  samples/               # CSV templates: cutoffs, seat matrix, fees, questions
deploy/                  # production compose, Caddyfile, backup.py
docs/
```

## Run it locally

Requirements: Python 3.12+ (tested on 3.14). No Node.js needed.

```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # optional; defaults work for development
alembic upgrade head
python -m app.seed                # --no-demo: reference data only; --remove-demo: delete demo data
uvicorn app.main:app --port 8000   # website and API at http://localhost:8000
```

- **Changing the look:** after editing templates or `app/web/styles/input.css`, rebuild the stylesheet with
  `python -m app.web.build_css` (downloads the Tailwind CLI once via `pytailwindcss`). The built
  `app/web/static/app.css` is committed, so deploying needs no build step.
- **Demo accounts** (development only, created by the seed): `student@demo.test` and `admin@demo.test`. The
  password is `SEED_DEMO_PASSWORD` from `.env.example`.
- **Emails in development:** with `EMAIL_BACKEND=console` (default), emails such as guardian-consent links are
  logged and saved in `backend/storage/outbox/`.
- **Windows note:** in a very deep folder, SQLAlchemy's compiled modules can exceed the 260-character path limit
  (`DLL load failed … filename or extension is too long`). Put the virtualenv in a short path (e.g. `C:\venvs\neet`)
  or enable Windows long paths.
- **Optional services:** `docker compose up -d` starts PostgreSQL and Redis for local testing.

### Tests

```bash
cd backend && python -m pytest -q             # 111 passed, 1 skipped (real-Tesseract test needs the binary)
cd backend && python -m playwright install chromium && python -m pytest e2e -q   # 14 browser tests
```

The browser tests start their own copy of the site (fresh SQLite database, via `backend/scripts/e2e_server.py`) on
port 8766, so they never touch the development database.

## Practice tests

- **Format:** taken from the NEET-UG 2025 bulletin, kept in `exams.NEET_PATTERN` (verify it each year).
  - 180 questions in 180 minutes: Physics 45, Chemistry 45, Botany 45, Zoology 45.
  - Marking is +4 / −1 / 0.
- **Test types:**
  - Full mock
  - Mini mock (same format, 5–20 questions per section)
  - Subject practice, including Biology as Botany + Zoology
  - Chapter tests (up to 10 chapters)
  - "My weak chapters": chapters under 60% from past tests
- **Exam day:** the paper is prepared first and stays sealed: no questions are visible and the clock is not running.
  Then come three steps:
  1. A practice admit card with roll number, paper, duration and centre.
  2. Instructions written like NTA's.
  3. OMR particulars: the student copies the roll number and darkens the Test Booklet Code, which must match.
  "Break the seal" starts the clock, with optional full screen and a bell.
- **Exam room:**
  - Printed-booklet look (serif type on paper colour), with questions numbered 1–180 continuously.
  - Match-the-list questions shown as List-I / List-II tables; options printed as (1)–(4).
  - A separate OMR answer sheet with roll number and booklet code.
  - Mark for review; optional **strict OMR mode** (a filled bubble cannot be changed, like the real answer sheet).
  - Invigilator announcements with a bell at 30, 10 and 5 minutes, and at "pens down".
  - A rough-work sheet you can draw on, not graded or saved.
  - Leaving the exam window is noted in the result.
- **Integrity:**
  - Answer keys stay on the server until submission.
  - Every answer is saved as it is given, so a refresh or dropped connection loses nothing.
  - The deadline is enforced on the server; late attempts are submitted automatically.
  - Correct answers are copied into the attempt, so later edits to the question bank don't change past results.
- **Results:**
  - Score, correct / wrong / blank, and marks lost to negative marking.
  - Section and chapter accuracy, and time per question.
  - Advice, plus a review of every answer with explanations.
  - Full mocks are added to the mock-test trend.
- **No repeated questions:** each student only ever gets questions they have not seen in any earlier test.
  - Each section's questions are spread across chapters in proportion to the syllabus, like the real paper.
  - Formats mix like NEET: single answer, statement-based, assertion–reason and match the lists.
  - When a student's unseen pool drops below `UNSEEN_BUFFER_PER_SECTION` (60), new questions are written in the
    background.
  - If a paper can't be built yet, the page shows "preparing fresh questions" and retries until it can.
- **How new questions are made** (`services/question_gen.py`):
  1. `QUESTION_WRITER_MODEL` (default Claude Haiku 5.5, via OpenRouter) writes original NCERT-based questions for
     one chapter at a time.
  2. Options are shuffled so answers spread across (1)–(4). Assertion–reason options keep their standard order.
  3. `QUESTION_CHECKER_MODEL` (default DeepSeek V4 Flash, a different provider) solves each question without seeing
     the key. A question is kept only if it reaches the same answer and rates the question unambiguous and within
     the syllabus.
  4. Near-duplicates and match questions whose answer is simply A-I, B-II, C-III, D-IV are dropped.
- **Measured cost:** about $0.0005 per kept question. The first run kept 560 of 578 drafts for $0.27.
- **Labels:** kept questions are stored as `ai_checked` and labelled "AI-written, independently checked, not
  expert-reviewed".
- **Reports:** students can report a problem on any question in their result. Two reports hide an unreviewed question
  until an admin decides (`GET /api/admin/questions/reports`, `PATCH /api/admin/questions/{id}`).
- **Command line:** `python -m app.maintenance grow-question-bank --per-section 100` adds questions in bulk.
- **Expert-reviewed questions:** load them with `POST /api/admin/questions/import` (template
  `samples/questions_template.csv`). The source's terms of use must allow it.
- **Sample questions:** the 80 original sample questions from development are retired by `--remove-demo`.

## Study plan

`POST /api/study-plan` builds a weekly plan from the student's class, the NEET date, their study hours and their
syllabus progress.

- **NEET date:** if the student doesn't enter it, the plan uses an estimate (first Sunday of May) and says so.
- **Class 11:** Class 11 chapters first, alongside school. Class 12 chapters start with the Class 12 school year in
  April. Then revision and full mocks.
- **Class 12:** Class 12 chapters first while revising Class 11. Board-exam weeks (mid-February to March) drop
  to light revision. Then a final phase of revision and mocks.
- **Dropper / repeater:** revision-led coverage of the whole syllabus, then mocks.
- **How tasks are scheduled:**
  - Subjects are interleaved each week.
  - Chapters are revised spaced apart, weak and least-revised first.
  - Chapters with low accuracy in practice tests get extra practice.
  - Full mocks start once most of the syllabus is done.
  - The share of time on new chapters rises when the student falls behind.
- **Warnings:** the plan warns when chapters don't fit before the final phase.
- **Syllabus tracker:** students mark chapters as not started, studied once, revised or confident, and the plan
  uses this. Ticking off study tasks moves chapters forward automatically.

## AI voice assistant

The assistant page has a mic button.

- **Speech in and out:** the browser's own speech services turn speech into text and read answers aloud. They are
  free, and no audio reaches our servers.
  - Supports English (India) and Hindi.
  - "Read answers aloud" and a hands-free mode, which listens again after each answer.
  - Works in Chrome, Edge and Safari; Firefox users can type.
- **Voice mode:** questions asked by voice are sent with `voice: true`. The model then answers in at most four
  plain spoken sentences, with no tables or links, and names sources in words. It replies in the student's
  language (English, Hindi or Hinglish).
- **Model:** OpenRouter with `anthropic/claude-haiku-5.5`. It was chosen from OpenRouter's live price list:
  - $0.10 per million input tokens and $0.50 per million output.
  - Fast, reliable at the multi-step tool calls the assistant depends on, and careful about instructions.
  - Measured cost is about $0.0005–0.002 per question (₹0.05–0.17), depending on how much data the tools return.
- **Fallbacks:** if Haiku is unavailable, OpenRouter tries `google/gemini-2.5-flash-lite`, then
  `openai/gpt-4.1-nano`. If OpenRouter fails, the grounded rule-based assistant answers.
- **Privacy:** requests set `provider.data_collection: deny`, so they go only to providers that don't store or
  train on prompts.
- **Cost logging:** every call logs its token use and cost.

## Around the campus

Nearby places come from OpenStreetMap (`PLACES_PROVIDER=overpass`, refreshed per college by an admin). They are
grouped into Getting around, Health & safety, Food, Stay, Daily needs, and Study & leisure.

- Each place shows its straight-line distance and, under 3 km, a rough walking time.
- Places are shown on a Leaflet map. Set `MAP_TILE_URL` and `MAP_ATTRIBUTION` to a tile provider you have a plan
  with for production traffic.
- Demo colleges have fictional locations, so their map is hidden.
- The page never claims a place is open, safe or has rooms.

## How the predictor works

1. Validate input. Official rank (AIR and/or state rank) **or** an explicitly estimated AIR *range*.
2. Filter cutoff records by course, quota (counselling route), seat type and **years before the exam year**.
3. Group into series of *(college, authority, quota, category, seat type)*. Routes are never mixed.
4. Eligibility.
   - Domicile-restricted state quota applies only to students of that state.
   - Reserved categories are compared with their own rows. They are compared with OPEN rows **only if** a
     **verified** `open_category_accessible` rule exists for that authority/year.
   - Demo rules apply to demo colleges only. A missing or unverified rule is reported, never assumed.
5. Compare like with like: AIR vs AIR, state rank vs state rank. Scores are never converted to ranks.
6. Use the final-round closing rank per year (latest N years, default 3):
   - **Stronger historical fit**: conservative rank ≤ 90% of the toughest year's closing rank
   - **Possible / uncertain**: within the range seen across years
   - **Ambitious**: up to 15% beyond the most lenient year
7. Confidence (`low` / `moderate` / `higher`) comes from the number of years and year-to-year volatility, and is
   capped for estimated ranks. No probabilities are shown.
8. Every row carries history, sources, verification status, an explanation, caveats and the cost estimate.
   Excluded options are counted with their reason.

## Data pipeline (admin)

`/admin` has tabs for **Overview** (go-live readiness), **Imports**, **Sources**, **Eligibility rules**,
**Info pages**, **Colleges** and **Issues & reviews**.

- **Terms of use first.** `POST /api/admin/imports/{cutoffs|seat_matrix|fees}` names a data source and is refused
  unless that source's terms review says `allowed`.
- **Import guarantees.**
  - The raw file is stored by SHA-256, and re-importing it changes nothing.
  - Values are normalised (`UR/GEN → OPEN`, `OBC-NCL → OBC`, `All India Quota → AIQ`, `PwD` → seat type) and
    validated (rank order, plausible years and amounts, quota run by that authority, `2025-26` academic years).
  - Unknown colleges are **not** auto-created; they raise data-quality issues.
  - A changed value on a **verified** record is not overwritten. The record becomes `conflicting`.
  - Rows for demo colleges are always stored as demo.
- **Documents.** PDFs and TXT are chunked with page numbers. Scanned pages are OCR'd when Tesseract is available,
  marked `extraction=ocr` and flagged for review. Otherwise they are flagged `needs_ocr`, with a retry button.
  Chunks are embedded when semantic search is configured.
- **Verification.** Records need a source URL or document to be verified. Every admin action is written to
  `audit_logs`.
- **Readiness.** `GET /api/admin/readiness` computes what still blocks real use, from data and config.

## Privacy & security

- **Accounts and sessions**
  - Passwords hashed with scrypt.
  - Session in an httpOnly, SameSite=Lax cookie.
  - **CSRF:** signed double-submit token (`neet_csrf` cookie, echoed as `X-CSRF-Token`) on every unsafe request.
- **Under-18s**
  - The student names a guardian, who receives a single-use consent link.
  - Personal-data features stay locked until the guardian approves.
  - Unanswered or refused accounts are purged after 7 days (`python -m app.maintenance purge-unconsented`).
  - Consents are logged in `consent_records`.
- **Personal data**
  - Category is optional, private, and used only for cutoff comparisons.
  - Data export: `GET /api/auth/me/export`. Hard delete: `DELETE /api/auth/me`.
- **Rate limits** per IP, shared through Redis when `REDIS_URL` is set (fails open to in-process limits).
- **Logs** are JSON-capable and carry request ids; they never include bodies or query strings.
- **Health checks:** `/api/health` (liveness) and `/api/ready` (database).
- **Production config** refuses to start with development secrets, insecure cookies, SQLite or console email.
- **Content safety:** reviews are held for moderation. Retrieved documents are treated as evidence, never as
  instructions.
- **Before launch:** legal review against the DPDP Act 2023. See [docs/DPDP_READINESS.md](docs/DPDP_READINESS.md).

## API

Interactive docs at `http://localhost:8000/docs`. Main endpoints:

| Area | Endpoints |
|---|---|
| Auth | `POST /api/auth/register · login · logout`, `GET /api/auth/me`, `GET /api/auth/me/export`, `DELETE /api/auth/me` |
| Guardian consent | `GET/POST /api/auth/guardian-consent/{token}`, `POST /api/auth/guardian-consent-resend` |
| Profile | `GET/PUT /api/profile`, `PUT /api/exam-profiles`, `POST /api/academic-records`, `GET /api/roadmap`, `POST /api/roadmap/generate` |
| Catalog | `GET /api/colleges`, `/colleges/facets`, `/colleges/{id}`, `/colleges/{id}/cost`, `POST /colleges/{id}/reviews` |
| Predictor | `POST /api/predict`, `POST /api/preference-lists/draft` |
| Compare | `POST /api/compare`, `GET /api/compare/priorities`, saved colleges `GET/POST/DELETE /api/saved-colleges/{id}` |
| Mock tests | `GET/POST /api/mock-tests`, `DELETE /api/mock-tests/{id}`, `GET /api/mock-tests/analytics` |
| Practice tests | `GET /api/exams/pattern`, `GET/POST /api/exams/attempts`, `GET /api/exams/attempts/{id}`, `PUT …/answers/{n}`, `POST …/submit · …/focus-lost`, `GET /api/exams/performance` |
| Study plan | `GET /api/syllabus`, `GET /api/syllabus/progress`, `PUT /api/syllabus/progress/{chapter}`, `GET/POST /api/study-plan`, `PATCH /api/study-plan/tasks/{id}` |
| Counselling | `GET /api/counselling/authorities`, `/counselling/rounds`, `/info/{section}`, preference lists CRUD |
| Assistant | `POST /api/assistant/messages`, `GET /api/assistant/sessions[/{id}]` |
| Admin | `/api/admin/readiness · stats · imports/{kind} · questions/import · questions/summary · questions/{id} · imports · documents[/{id}/ocr] · embeddings/backfill · data-sources[/{id}/terms] · eligibility-rules · info-articles/{id} · colleges[/{id}] · colleges/{id}/nearby/refresh · issues · verify · reviews · audit` |
| Ops | `GET /api/health`, `GET /api/ready` |

## Status

| Area | Status |
|---|---|
| Foundation, predictor, college intelligence, mock tests, assistant | ✅ Done |
| Importers for cutoffs, seat matrices and fees, with a terms-of-use gate | ✅ Done |
| Admin workflows: eligibility rules, info-page review, source terms, readiness checklist | ✅ Done |
| OCR (Tesseract), semantic search (Voyage + BM25), nearby places (OpenStreetMap) | ✅ Built. Each needs its key/binary/provider switched on |
| CSRF, shared rate limiting, guardian consent, retention job, production config guard | ✅ Done |
| Practice tests (NEET format, OMR sheet, analysis) and class-based study plans | ✅ Done. **Needs an expert-reviewed question bank** before launch |
| Around-the-campus facilities with map | ✅ Done. Needs real colleges with verified coordinates |
| Website in Python (Jinja2 + HTMX, served by FastAPI) | ✅ Done |
| Browser tests (Playwright for Python) | ✅ 14 tests |
| Deployment (Docker, HTTPS, backups, monitoring) | ✅ Written; not yet run on a server |
| **Real data** | ⏳ Needs the source terms review and the import and verification work in [DATA_LOADING.md](docs/DATA_LOADING.md) |
| **Legal review (DPDP)** | ⏳ Needs a qualified lawyer: [DPDP_READINESS.md](docs/DPDP_READINESS.md) |
