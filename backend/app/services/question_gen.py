"""AI question generation with an independent answer check.

Pipeline for each batch (one syllabus chapter at a time):
1. A writer model drafts original NEET-UG style MCQs in the four NEET styles (single correct,
   statement-based, assertion–reason, match the lists), grounded in the NCERT chapter.
2. Options are shuffled (except assertion–reason, whose options have a fixed conventional order), so
   correct answers are spread evenly across options 1–4.
3. A checker model from a different provider solves each question without seeing the key. A question
   is kept only if the checker reaches the same answer, rates it unambiguous and within the syllabus.
4. Near-duplicates of existing questions in the chapter are dropped.
Kept questions are stored as review_status="ai_checked" and shown to students with a label; students
can report problems, and two reports hide a question until an admin looks at it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Question, SyllabusChapter, VerificationStatus

log = logging.getLogger(__name__)
URL = "https://openrouter.ai/api/v1/chat/completions"
FORMATS = ("single", "statements", "assertion_reason", "match")
AR_OPTIONS = [
    "Both A and R are true and R is the correct explanation of A.",
    "Both A and R are true but R is NOT the correct explanation of A.",
    "A is true but R is false.",
    "A is false but R is true.",
]

WRITER_PROMPT = """You write original practice questions for NEET-UG, India's medical entrance exam.

Write {n} multiple-choice questions on the NCERT Class {cls} {subject} chapter "{chapter}".
Rules:
- NEET-UG standard: test understanding and application of the NCERT content, not trivia. {subject_rule}
- Original wording. Do not copy questions from past NEET papers, coaching books or websites.
- Exactly four options and exactly ONE correct answer. Distractors must be plausible but clearly wrong
  to someone who knows the concept. No "all of the above" / "none of the above".
- Mix the NEET question styles across the batch:
  - "single": a direct question.
  - "statements": two to four numbered statements (on separate lines, "A. ...", "B. ...") and options
    such as "A and B only".
  - "assertion_reason": stem has a line "Assertion (A): ..." and a line "Reason (R): ...". Options must be
    exactly the four standard assertion–reason options (any order is fine; they will be normalised).
    Vary which of the four is correct: false assertions, false reasons and true-but-unrelated reasons are as
    common in NEET as "R explains A".
  - "match": "Match List-I with List-II" followed by lines "A. item | I. item" (four rows), and options
    such as "A-II, B-I, C-IV, D-III". List-II must be scrambled, so the correct answer is never
    "A-I, B-II, C-III, D-IV".
  Aim for roughly: {format_mix}.
- Difficulty mix: about 40% easy, 45% medium, 15% hard. Numericals must use clean numbers and SI units.
- Use plain text (Unicode for subscripts/superscripts like H₂O, 10⁻³, x²); no LaTeX, no images.
- explanation: 1–3 sentences showing why the answer is right.
- Avoid repeating these existing questions in this chapter:
{avoid}
Return JSON only."""

CHECKER_PROMPT = """You are checking a NEET-UG practice question before students see it.
Solve it yourself carefully. Then judge it.

Question:
{stem}

Options:
1. {o1}
2. {o2}
3. {o3}
4. {o4}

Return JSON: {{"answer": <1-4, your answer>, "confident": <true if you are sure>,
"unambiguous": <true if exactly one option is defensibly correct>, "in_syllabus": <true if it fits the NEET-UG
NCERT syllabus>, "issue": "<short note if anything is wrong, else empty>"}}"""

GEN_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["questions"],
    "properties": {"questions": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["format", "topic", "difficulty", "stem", "options", "answer", "explanation"],
        "properties": {
            "format": {"type": "string", "enum": list(FORMATS)},
            "topic": {"type": "string"},
            "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
            "stem": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
            "answer": {"type": "integer", "description": "1-4"},
            "explanation": {"type": "string"},
        }}}},
}
CHECK_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["answer", "confident", "unambiguous", "in_syllabus", "issue"],
    "properties": {"answer": {"type": "integer"}, "confident": {"type": "boolean"},
                   "unambiguous": {"type": "boolean"}, "in_syllabus": {"type": "boolean"}, "issue": {"type": "string"}},
}
SUBJECT_RULE = {
    "Botany": "Biology questions should follow NCERT statements and facts closely.",
    "Zoology": "Biology questions should follow NCERT statements and facts closely.",
    "Physics": "Include conceptual and numerical questions solvable in about a minute without a calculator.",
    "Chemistry": "Cover physical (numerical), organic (reactions, mechanisms) and inorganic (trends, facts) as the chapter needs.",
}


class GenerationError(RuntimeError):
    pass


@dataclass
class BatchResult:
    chapter: str
    drafted: int = 0
    kept: int = 0
    rejected: list[str] = field(default_factory=list)
    cost_usd: float = 0.0


def enabled() -> bool:
    s = get_settings()
    return bool(s.openrouter_api_key) and s.question_gen_enabled


def _client() -> httpx.Client:
    s = get_settings()
    return httpx.Client(timeout=120, headers={"Authorization": f"Bearer {s.openrouter_api_key}",
                                              "HTTP-Referer": s.public_app_url, "X-Title": "NEET Compass question bank"})


def _call(client: httpx.Client, model: str, prompt: str, schema: dict, name: str, max_tokens: int,
          temperature: float) -> tuple[dict, float]:
    r = client.post(URL, json={
        "model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
        "temperature": temperature, "usage": {"include": True},
        "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}})
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise GenerationError(str(data["error"]))
    content = data["choices"][0]["message"].get("content") or ""
    content = re.sub(r"^```(?:json)?|```$", "", content.strip()).strip()
    return json.loads(content), float((data.get("usage") or {}).get("cost") or 0)


def _norm_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - {"the", "a", "an", "of", "is", "which", "following", "and", "in", "to"}


def _similar(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def content_hash(stem: str, options: list[str]) -> str:
    return hashlib.sha256(json.dumps([stem.strip(), [o.strip() for o in options]]).encode()).hexdigest()


def _clean(q: dict, rng: random.Random) -> tuple[dict | None, str]:
    """Validate a drafted question and shuffle its options. Returns (question, rejection reason)."""
    opts = [str(o).strip() for o in q.get("options") or []]
    stem = str(q.get("stem") or "").strip()
    ans = q.get("answer")
    if len(opts) != 4 or not stem or not isinstance(ans, int) or not 1 <= ans <= 4:
        return None, "malformed"
    if len({o.lower() for o in opts}) < 4 or any(not o for o in opts):
        return None, "duplicate or empty options"
    if any(re.search(r"\b(all|none) of the above\b", o, re.I) for o in opts):
        return None, "all/none of the above"
    fmt = q.get("format") if q.get("format") in FORMATS else "single"
    correct_text = opts[ans - 1]
    if fmt == "assertion_reason":
        # Map onto the standard option order used in the exam.
        def key(o):
            o = o.lower()
            if "not the correct explanation" in o or "not a correct explanation" in o:
                return 1
            if "correct explanation" in o:
                return 0
            if re.search(r"\ba is true\b.*\br is false\b", o):
                return 2
            if re.search(r"\ba is false\b.*\br is true\b", o):
                return 3
            return -1
        keys = [key(o) for o in opts]
        if sorted(keys) != [0, 1, 2, 3]:
            return None, "non-standard assertion–reason options"
        correct = keys[ans - 1]
        opts = AR_OPTIONS[:]
    else:
        rng.shuffle(opts)
        correct = opts.index(correct_text)
    return {"format": fmt, "topic": str(q.get("topic") or "")[:150], "stem": stem, "options": opts,
            "correct_index": correct, "explanation": str(q.get("explanation") or "").strip(),
            "difficulty": q.get("difficulty") if q.get("difficulty") in ("easy", "medium", "hard") else "medium"}, ""


def generate_batch(db: Session, chapter: SyllabusChapter, n: int = 6, rng: random.Random | None = None,
                   client: httpx.Client | None = None) -> BatchResult:
    """Draft, check and store up to n new questions for one chapter."""
    s = get_settings()
    rng = rng or random.Random()
    res = BatchResult(chapter=chapter.name)
    existing = list(db.scalars(select(Question).where(Question.chapter_id == chapter.id)))
    avoid = "\n".join(f"- {q.stem.splitlines()[0][:110]}" for q in existing[-40:]) or "- (none yet)"
    fmt_mix = ("4 single, 1 statements, 1 match" if chapter.subject in ("Physics",) else
               "3 single, 1 statements, 1 assertion_reason, 1 match")
    own_client = client is None
    client = client or _client()
    try:
        drafted, cost = _call(client, s.question_writer_model, WRITER_PROMPT.format(
            n=n, cls=chapter.class_level, subject="Biology" if chapter.subject in ("Botany", "Zoology") else chapter.subject,
            chapter=chapter.name, subject_rule=SUBJECT_RULE.get(chapter.subject, ""), format_mix=fmt_mix, avoid=avoid),
            GEN_SCHEMA, "neet_questions", 6000, 0.8)
        res.cost_usd += cost
        candidates = drafted.get("questions") or []
        res.drafted = len(candidates)
        seen_tokens = [_norm_tokens(q.stem) for q in existing]
        hashes = set(db.scalars(select(Question.content_hash)))

        cleaned = []
        for raw in candidates:
            q, why = _clean(raw, rng)
            if q is None:
                res.rejected.append(why)
                continue
            toks = _norm_tokens(q["stem"])
            if any(_similar(toks, t) > 0.75 for t in seen_tokens):
                res.rejected.append("near-duplicate")
                continue
            seen_tokens.append(toks)
            cleaned.append(q)

        def check(q):
            o = q["options"]
            return _call(client, s.question_checker_model, CHECKER_PROMPT.format(stem=q["stem"], o1=o[0], o2=o[1], o3=o[2], o4=o[3]),
                         CHECK_SCHEMA, "check", 4000, 0.0)

        def check_with_retry(q):
            return _safe(check, q) or _safe(check, q)  # one retry: checkers occasionally return empty output

        with ThreadPoolExecutor(max_workers=6) as pool:
            verdicts = list(pool.map(check_with_retry, cleaned))

        for q, verdict in zip(cleaned, verdicts):
            if verdict is None:
                res.rejected.append("checker error")
                continue
            v, cost = verdict
            res.cost_usd += cost
            if q["format"] == "match" and re.search(r"A-I,\s*B-II,\s*C-III,\s*D-IV", q["options"][q["correct_index"]]):
                res.rejected.append("match answer in list order")
                continue
            if v.get("answer") != q["correct_index"] + 1:
                res.rejected.append("checker disagreed with the answer key")
                continue
            if not (v.get("confident") and v.get("unambiguous") and v.get("in_syllabus")):
                res.rejected.append("checker: " + (v.get("issue") or "ambiguous or out of syllabus")[:80])
                continue
            h = content_hash(q["stem"], q["options"])
            if h in hashes:
                res.rejected.append("exact duplicate")
                continue
            hashes.add(h)
            db.add(Question(
                subject=chapter.subject, chapter_id=chapter.id, topic=q["topic"] or None, difficulty=q["difficulty"],
                stem=q["stem"], options=q["options"], correct_index=q["correct_index"], explanation=q["explanation"] or None,
                qformat=q["format"], review_status="ai_checked", content_hash=h,
                generated_by=s.question_writer_model, checked_by=s.question_checker_model,
                source_name="AI-written practice question; answer independently checked by a second AI model. Not expert-reviewed.",
                verification_status=VerificationStatus.unverified))
            res.kept += 1
        db.commit()
    finally:
        if own_client:
            client.close()
    log.info("question-gen chapter=%s drafted=%d kept=%d cost_usd=%.5f rejected=%s",
             chapter.code, res.drafted, res.kept, res.cost_usd, res.rejected)
    return res


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as exc:  # noqa: BLE001 - one bad check must not lose the batch
        log.warning("question check failed: %s", exc)
        return None


# ---------------------------------------------------------------- keeping the bank topped up

_lock = threading.Lock()
_running: set[str] = set()


def unseen_counts(db: Session, user_id: int) -> dict[str, int]:
    from app.models import ExamAttempt, ExamAttemptItem
    from app.services.exams import SERVED
    seen = select(ExamAttemptItem.question_id).join(ExamAttempt).where(ExamAttempt.user_id == user_id)
    rows = db.execute(select(Question.subject, func.count()).where(
        Question.review_status.in_(SERVED), Question.id.not_in(seen)).group_by(Question.subject)).all()
    return dict(rows)


def pick_chapters(db: Session, subject: str, batches: int, rng: random.Random) -> list[SyllabusChapter]:
    """Chapters to write for, weighted by syllabus size and favouring chapters with few questions."""
    chapters = list(db.scalars(select(SyllabusChapter).where(SyllabusChapter.subject == subject)))
    have = dict(db.execute(select(Question.chapter_id, func.count()).where(Question.subject == subject)
                           .group_by(Question.chapter_id)).all())
    weights = [c.est_hours / (1 + have.get(c.id, 0) / 6) for c in chapters]
    return rng.choices(chapters, weights=weights, k=batches)


def top_up(subjects_needed: dict[str, int], session_factory, per_batch: int = 6) -> None:
    """Generate at least the given number of new questions per subject. Safe to call repeatedly:
    a subject already being generated is skipped."""
    with _lock:
        todo = {s: n for s, n in subjects_needed.items() if n > 0 and s not in _running}
        _running.update(todo)
    if not todo:
        return
    try:
        rng = random.Random()
        with session_factory() as db, _client() as client:
            jobs = []
            for subject, n in todo.items():
                # About two-thirds of drafts survive checking, so over-generate.
                batches = max(1, -(-int(n * 1.6) // per_batch))
                jobs += [(c.id, subject) for c in pick_chapters(db, subject, batches, rng)]

        def run(job):
            chapter_id, _ = job
            with session_factory() as db2, _client() as c2:
                return generate_batch(db2, db2.get(SyllabusChapter, chapter_id), per_batch, client=c2)

        with ThreadPoolExecutor(max_workers=get_settings().question_gen_workers) as pool:
            for r in pool.map(lambda j: _safe(run, j), jobs):
                if r is None:
                    log.warning("question-gen batch failed")
    finally:
        with _lock:
            _running.difference_update(todo)


def is_generating(subject: str | None = None) -> bool:
    with _lock:
        return bool(_running) if subject is None else subject in _running


def start_top_up(subjects_needed: dict[str, int]) -> bool:
    """Run top_up in a background thread. Returns False when generation is disabled."""
    if not enabled():
        return False
    from app.db import SessionLocal
    threading.Thread(target=_safe, args=(top_up, subjects_needed, SessionLocal), daemon=True).start()
    return True


def top_up_chapters(chapter_ids: list[int], n: int, session_factory, per_batch: int = 6) -> None:
    """Generate about n new questions spread over specific chapters (chapter and weak-chapter tests)."""
    key = "chapters:" + ",".join(map(str, sorted(chapter_ids)))
    with _lock:
        if key in _running:
            return
        _running.add(key)
    try:
        batches = max(1, -(-int(n * 1.6) // per_batch))
        jobs = [chapter_ids[i % len(chapter_ids)] for i in range(batches)]

        def run(chapter_id):
            with session_factory() as db2, _client() as c2:
                return generate_batch(db2, db2.get(SyllabusChapter, chapter_id), per_batch, client=c2)

        with ThreadPoolExecutor(max_workers=get_settings().question_gen_workers) as pool:
            list(pool.map(lambda j: _safe(run, j), jobs))
    finally:
        with _lock:
            _running.discard(key)


def start_top_up_chapters(chapter_ids: list[int], n: int) -> bool:
    if not enabled():
        return False
    from app.db import SessionLocal
    threading.Thread(target=_safe, args=(top_up_chapters, chapter_ids, n, SessionLocal), daemon=True).start()
    return True
