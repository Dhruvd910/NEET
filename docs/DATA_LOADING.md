# Loading real data

The platform ships with **no real college data**. This is the runbook for loading it. The tools enforce
the order: imports are refused until a source's terms are reviewed, unverified rules are ignored by the
predictor, and **/admin → Overview** lists what is still missing.

## 0. Start clean

Production: seed with `python -m app.seed --no-demo`. If a database already has demo data, remove it first
with `python -m app.seed --remove-demo`. This deletes demo colleges and everything attached to them, demo rules
and the demo accounts. Demo rules on MCC/KEA would otherwise block entering the real ones.

## 1. Review each source's terms of use (/admin → Sources)

For every website you take data from, read its terms, copyright or reuse policy, and record:

- **usage status:** `allowed`, `restricted` or `prohibited`
- the terms URL
- what the terms allow
- any required attribution
- whether automated downloading is allowed

Imports name a source and are refused unless that source is `allowed`. Typical sources:

| Data | Where it is published | Notes |
|---|---|---|
| College list, recognition, seats | National Medical Commission (nmc.org.in): list of colleges and permitted seats | Use it to create colleges and their codes |
| AIQ / deemed / central allotments and closing ranks | Medical Counselling Committee (mcc.nic.in): round-wise results and seat matrix PDFs | One file per round; use the final round per year |
| State quota allotments | Each state's counselling authority (KEA, Maharashtra CET Cell, TN Selection Committee, …) | Check whether state merit rank or AIR is used |
| Exam rules, pattern, eligibility | NTA Information Bulletin (neet.nta.nic.in) for the exam year | Upload the PDF as a document first |
| Fees | College prospectus, state fee-regulatory committee orders | Record the academic year exactly as printed |

The table is a starting point, not legal advice. Check each site yourself, because terms and URLs change.

## 2. Create colleges (/admin → Colleges)

Use the official name and a stable code. Add every spelling used in allotment lists as an alias, because
imports match on code, then alias, then exact normalised name. Unknown names are **never** auto-created;
they become `unknown_college` issues. Enter coordinates only from a verified source; they drive nearby places.

## 3. Convert PDFs to CSV

Allotment and seat-matrix PDFs are tables. Extract them with a table tool (e.g. Tabula or Camelot), or by hand
for small files, into the templates in `backend/samples/`:

- `cutoffs_template.csv`: `college_code|college_name, course, authority, exam_year, round, quota, category,
  closing_rank` (+ `opening_rank, seat_type, rank_basis, domicile_required, round_name`)
- `seat_matrix_template.csv`: `… quota, category, seats` (+ `seat_type`)
- `fees_template.csv`: `college_code|college_name, academic_year, fee_type, amount_inr, period` (+ `course,
  quota, mandatory, refundable, note`)

Category and quota spellings are normalised on import (`UR/GEN → OPEN`, `OBC-NCL → OBC`,
`All India Quota → AIQ`, `PwD` suffix → seat type `PWD`). **Never import numbers from OCR text without
checking them against the original page.** OCR'd passages are marked and raise an
`ocr_text_needs_review` issue.

## 4. Import, then review (/admin → Imports, Issues & reviews)

- Re-importing the same file changes nothing. A corrected file updates unverified rows only.
- A change to a **verified** row is not applied. The row becomes `conflicting` and needs a decision.
- Work through every issue: add missing colleges or aliases, fix rows, re-import.

## 5. Verify

Verification means a person has compared the record with the official source. Recommended policy:

- Check a sample from every import, including the first and last rows and at least 5% of the rest. Use a second
  person for anything the predictor relies on (closing ranks, rules).
- Mark records verified with `POST /api/admin/verify` (the UI does this for rules and info pages). Verifying
  needs a source URL or an uploaded source document. Demo records can never be verified.
- Mark superseded records `outdated` instead of deleting them, so the history stays intact.

## 6. Reserved-category OPEN-seat rules (/admin → Eligibility rules)

For each authority × exam year × quota with real cutoffs, read the official counselling scheme and enter
`open_category_accessible`:

- `true`: reserved-category candidates may also take OPEN seats on merit.
- `false`: they may not.

Include the source document and clause. The "Missing rules" list shows every combination still to do; click
one to prefill the form. Rules start **unverified** and the predictor ignores them until they are verified.
Until then, reserved-category students are compared only with their own category's cutoffs, and the results
say so.

## 7. NEET info pages (/admin → Info pages)

Upload the current NTA Information Bulletin (Imports → document). Then, for each page:

1. Compare the text with the bulletin and edit it where needed.
2. Set the exam year and the bulletin as the source.
3. Mark it verified.

Any later edit sends the page back to "pending verification".

## 8. Nearby places (optional)

Set `PLACES_PROVIDER=overpass` and a real contact address in `PLACES_USER_AGENT`. Then, for each college with
verified coordinates, use **Colleges → Refresh nearby places**. Data comes from OpenStreetMap (ODbL) and is
shown with attribution. Only straight-line distance is stored; opening hours and availability are never claimed.

## 9. Question bank

The 80 bundled questions are original samples for development and are labelled "not expert-reviewed". Before
launch, load a reviewed bank:

1. **Get the rights.** Commercial question banks and coaching material are copyrighted. Use questions you wrote,
   commissioned or licensed, and record the source on the Sources tab.
2. **Fill the template.** Use `backend/samples/questions_template.csv`:
   - chapter code from the syllabus (e.g. `PHY-11-04`), topic, difficulty
   - the question and four options
   - `answer` as 1–4, and an explanation
3. **Import and review.** Use `POST /api/admin/questions/import`. Rows are stored as **drafts**, which are never
   shown to students, unless you confirm a subject expert checked every answer key.
   - To promote or retire single questions: `PATCH /api/admin/questions/{id}`.
   - To retire the samples: `python -m app.seed --remove-demo`.
4. **Check coverage.** A full mock needs 45 served questions per section. The readiness checklist tracks this.

Also check the syllabus chapter list (seeded as "pending verification") against the current NMC/NTA syllabus.

## 10. Go live

When **/admin → Overview** has no "to do" items, the data side is ready. The legal review item is described in
[DPDP_READINESS.md](DPDP_READINESS.md).
