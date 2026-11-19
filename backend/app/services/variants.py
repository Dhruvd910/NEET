"""New versions of questions already in the bank, written by free models.

A writer model rewrites a question so it tests the same idea with new numbers (numericals) or new wording and
statement order (theory). A second free model solves the new version without seeing the key; only versions where
both agree are kept. Versions of previous-year questions go into mocks, so mocks stay at NEET level without ever
showing the exact paper again. Free models are rate-limited (about 20 calls a minute, 1000 a day), so this runs
slowly in the background.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.config import get_settings
from app.models import Question, VerificationStatus
from app.services.question_gen import CHECKER_PROMPT, URL, _client, _clean, _norm_tokens, content_hash

log = logging.getLogger(__name__)

WRITER_PROMPT = """Rewrite this NEET-UG question so a student who has seen it meets a new question on the same idea.
- If it has numbers, change them to new realistic values that keep the arithmetic easy, and recompute the answer.
- Otherwise reword it, reorder statements or list items, and change which facts the options use, staying within NCERT.
- Keep the same style ({fmt}), the same difficulty and exactly four options; only one may be correct.
- Then solve your new version carefully and give its correct option.

Question:
{stem}

Options:
1. {o1}
2. {o2}
3. {o3}
4. {o4}

Reply with JSON only: {{"stem": "...", "options": ["", "", "", ""], "answer": <1-4>, "explanation": "<short working>"}}"""


class DailyLimit(Exception):
    """The free models' daily quota is used up; it resets at midnight UTC."""


def _ask(client: httpx.Client, model: str, prompt: str, temperature: float) -> dict | None:
    """One free-model call, reading the first JSON object in the reply (free models rarely support strict JSON
    mode). Waits and retries once when the free pool is busy. None when it fails."""
    for wait in (0, 30):
        time.sleep(wait)
        try:
            r = client.post(URL, json={"model": model, "messages": [{"role": "user", "content": prompt}],
                                       "max_tokens": 4000, "temperature": temperature}, timeout=180)
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("variant call to %s failed: %s", model, e)
            continue
        if "per-day" in str(data.get("error", "")):
            raise DailyLimit(str(data["error"])[:160])
        if r.status_code == 429 or "choices" not in data:
            log.info("variant call to %s: %s", model, str(data.get("error", data))[:120])
            continue
        m = re.search(r"\{.*\}", data["choices"][0]["message"].get("content") or "", re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except ValueError:
            return None
    return None


def _sources(db: Session, limit: int) -> list[Question]:
    """Questions to rewrite: served, not a version themselves, with the fewest versions so far; previous-year
    questions first (NEET level), then harder ones."""
    from app.services.exams import SERVED
    v = aliased(Question)
    versions = select(func.count()).where(v.variant_of == Question.id).scalar_subquery()
    return list(db.scalars(select(Question).where(Question.review_status.in_(SERVED), Question.variant_of.is_(None))
                           .order_by(versions, Question.pyq_year.is_(None), Question.difficulty == "easy", func.random())
                           .limit(limit)))


def make_variant(db: Session, src: Question, client: httpx.Client, rng: random.Random) -> str:
    """Write, check and store one new version of src. Returns "kept" or why it was dropped."""
    s = get_settings()
    o = src.options
    raw = _ask(client, s.variant_writer_model, WRITER_PROMPT.format(fmt=src.qformat.replace("_", "-"), stem=src.stem,
                                                                    o1=o[0], o2=o[1], o3=o[2], o4=o[3]), 0.7)
    if raw is None:
        return "writer gave no answer"
    q, why = _clean({**raw, "format": src.qformat, "topic": src.topic, "difficulty": src.difficulty}, rng)
    if q is None:
        return why
    h = content_hash(q["stem"], q["options"])
    same = _norm_tokens(q["stem"]) == _norm_tokens(src.stem) and sorted(q["options"]) == sorted(src.options)
    if same or db.scalar(select(Question.id).where(Question.content_hash == h)):
        return "not changed"
    o = q["options"]
    prompt = CHECKER_PROMPT.format(stem=q["stem"], o1=o[0], o2=o[1], o3=o[2], o4=o[3])
    for model in s.variant_checker_models:
        v = _ask(client, model, prompt, 0.0)
        if v is not None:
            break
    else:
        return "no checker available"
    if v.get("answer") != q["correct_index"] + 1:
        return "checker disagreed"
    if not (v.get("confident") and v.get("unambiguous") and v.get("in_syllabus")):
        return "checker: " + str(v.get("issue") or "unsure")[:60]
    db.add(Question(
        subject=src.subject, chapter_id=src.chapter_id, topic=src.topic, difficulty=src.difficulty,
        stem=q["stem"], options=q["options"], correct_index=q["correct_index"], explanation=q["explanation"] or None,
        qformat=q["format"], review_status="ai_checked", content_hash=h, variant_of=src.id,
        generated_by=s.variant_writer_model, checked_by=model,
        source_name="New version of a bank question (numbers or wording changed by AI); answer checked by a second "
                    "AI model. Not expert-reviewed.",
        verification_status=VerificationStatus.unverified))
    db.commit()
    return "kept"


def make_variants(db: Session, limit: int) -> dict:
    """Up to `limit` new versions, one per source question, pacing calls to the free-model rate limit."""
    rng, out = random.Random(), {}
    with _client() as client:
        for src in _sources(db, limit):
            started = time.monotonic()
            try:
                why = make_variant(db, src, client, rng)
            except DailyLimit:
                out["stopped: free daily limit reached"] = 1
                break
            out[why] = out.get(why, 0) + 1
            time.sleep(max(0.0, 7 - (time.monotonic() - started)))  # two calls per question; free pool allows ~20/min
    log.info("variants: %s", out)
    return out
