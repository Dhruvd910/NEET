"""Learning progress per subject and overall: chapters covered (from the student's own chapter tracker), test
accuracy, last activity, weak chapters, and a finish estimate from the student's own recent pace."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChapterProgress, ExamAttempt, SyllabusChapter
from app.services.admin_activity import IST, _ist
from app.services.exams import SECTIONS, chapter_accuracy

# Share of a chapter's study hours counted as covered, by the student's own status.
CREDIT = {"not_started": 0.0, "learning": 0.5, "revised": 1.0, "mastered": 1.0}
PACE_DAYS = 30  # pace = hours covered over the last 30 days (or since the first entry, if newer)


def _eta(remaining_h: float, pace_h_per_day: float) -> dict | None:
    if remaining_h <= 0:
        return {"days": 0, "finish": datetime.now(IST).date()}
    if pace_h_per_day <= 0:
        return None
    days = round(remaining_h / pace_h_per_day)
    return {"days": days, "finish": datetime.now(IST).date() + timedelta(days=days)}


def progress(db: Session, user_id: int) -> dict:
    chapters = db.scalars(select(SyllabusChapter).order_by(SyllabusChapter.sort_order)).all()
    rows = {r.chapter_id: r for r in db.scalars(select(ChapterProgress).where(ChapterProgress.user_id == user_id))}
    acc = chapter_accuracy(db, user_id)
    now = datetime.now(timezone.utc)
    first = min((_ist(r.updated_at) for r in rows.values()), default=None)
    window = max(7, min(PACE_DAYS, (now.astimezone(IST) - first).days + 1)) if first else PACE_DAYS
    since = now - timedelta(days=window)
    last_test = db.scalar(select(ExamAttempt.submitted_at).where(ExamAttempt.user_id == user_id,
                                                                 ExamAttempt.status == "submitted")
                          .order_by(ExamAttempt.submitted_at.desc()))

    subjects = {s: {"name": s, "chapters": 0, "covered": 0, "hours": 0.0, "done_h": 0.0, "recent_h": 0.0,
                    "attempted": 0, "correct": 0, "last": None, "weak": []} for s in SECTIONS}
    for c in chapters:
        s = subjects.get(c.subject)
        if s is None:
            continue
        r = rows.get(c.id)
        credit = CREDIT.get(r.status, 0) if r else 0
        s["chapters"] += 1
        s["covered"] += credit == 1.0
        s["hours"] += c.est_hours
        s["done_h"] += credit * c.est_hours
        if r and credit and _ist(r.updated_at) >= since.astimezone(IST):
            s["recent_h"] += credit * c.est_hours
        if r and (s["last"] is None or _ist(r.updated_at) > s["last"]):
            s["last"] = _ist(r.updated_at)
        t = acc.get(c.id)
        if t:
            s["attempted"] += t["attempted"]
            s["correct"] += t["correct"]
            # "Where they lack": chapters answered wrong more often than right, once there is enough to judge.
            if t["attempted"] >= 2 and (t["accuracy"] or 0) < 60:
                s["weak"].append({"name": c.name, "accuracy": t["accuracy"], "attempted": t["attempted"]})

    def finish(s: dict) -> dict:
        s["percent"] = round(100 * s["done_h"] / s["hours"]) if s["hours"] else 0
        s["accuracy"] = round(100 * s["correct"] / s["attempted"]) if s["attempted"] else None
        s["pace_h_per_week"] = round(7 * s["recent_h"] / window, 1)
        s["eta"] = _eta(s["hours"] - s["done_h"], s["recent_h"] / window)
        s["weak"].sort(key=lambda w: w["accuracy"] or 0)
        return s

    subs = [finish(s) for s in subjects.values()]
    total = {"name": "Overall", "weak": [w for s in subs for w in s["weak"]], "last": None}
    for k in ("chapters", "covered", "hours", "done_h", "recent_h", "attempted", "correct"):
        total[k] = sum(s[k] for s in subs)
    finish(total)
    total["weak"] = total["weak"][:8]
    total["last"] = max([s["last"] for s in subs if s["last"]] + ([_ist(last_test)] if last_test else []), default=None)
    return {"subjects": subs, "overall": total, "pace_window_days": window}


def daily_quiz(db: Session, user_id: int) -> ExamAttempt | None:
    """Today's daily quiz (Indian date), if the student has started or prepared one."""
    start = datetime.combine(datetime.now(IST).date(), datetime.min.time(), IST).astimezone(timezone.utc)
    return db.scalars(select(ExamAttempt).where(ExamAttempt.user_id == user_id, ExamAttempt.mode == "daily",
                                                ExamAttempt.started_at >= start)
                      .order_by(ExamAttempt.id.desc())).first()
