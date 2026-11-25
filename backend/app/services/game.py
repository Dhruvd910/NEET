"""Game layer over practice tests: XP, combos, hearts, stars, levels and the daily-quiz streak. Everything is worked
out from the answers already stored, so there is nothing extra to save and old tests count too.

- A right answer earns 10 XP × the combo (answers right in a row, up to ×5).
- The daily quiz is played with 3 hearts: every wrong answer costs one, and the game ends at zero.
- Finishing any test adds 20 XP. Level n needs 100·(n−1)² XP in total (100, 400, 900 …).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import ExamAttempt, User
from app.services.admin_activity import IST
from app.services.exams import _aware

XP_RIGHT, COMBO_MAX, HEARTS, FINISH_BONUS = 10, 5, 3, 20


def run(a: ExamAttempt) -> dict:
    """Replay a test's answers in order: XP so far, current and best combo, hearts left, right/answered."""
    xp = combo = best = right = answered = 0
    hearts = HEARTS
    for i in sorted(a.items, key=lambda i: i.position):
        if i.selected_index is None:
            continue
        answered += 1
        if i.selected_index == i.correct_index:
            right += 1
            combo = min(combo + 1, COMBO_MAX)
            best = max(best, combo)
            xp += XP_RIGHT * combo
        else:
            combo, hearts = 0, hearts - 1
    if a.status == "submitted":
        xp += FINISH_BONUS
    return {"xp": xp, "combo": combo, "best": best, "hearts": max(hearts, 0), "right": right, "answered": answered,
            "total": len(a.items)}


def stars(a: ExamAttempt) -> int:
    pct = 100 * (a.score or 0) / a.max_score if a.max_score else 0
    return 3 if pct >= 80 else 2 if pct >= 50 else 1 if pct > 0 else 0


def level_of(xp: int) -> dict:
    n = int((xp / 100) ** 0.5) + 1
    lo, hi = 100 * (n - 1) ** 2, 100 * n ** 2
    return {"level": n, "xp": xp, "into": xp - lo, "span": hi - lo, "pct": round(100 * (xp - lo) / (hi - lo))}


def streak(db: Session, user_id: int, today=None) -> int:
    """Days in a row (Indian dates) with a finished daily quiz, counting back from today, or yesterday if today's
    quiz is not done yet."""
    days = {_aware(s).astimezone(IST).date() for s in db.scalars(select(ExamAttempt.submitted_at).where(
        ExamAttempt.user_id == user_id, ExamAttempt.mode == "daily", ExamAttempt.status == "submitted")) if s}
    d, n = today or datetime.now(IST).date(), 0
    if d not in days:
        d -= timedelta(days=1)
    while d in days:
        n, d = n + 1, d - timedelta(days=1)
    return n


def profile(db: Session, user: User) -> dict:
    done = db.scalars(select(ExamAttempt).where(ExamAttempt.user_id == user.id, ExamAttempt.status == "submitted")
                      .options(selectinload(ExamAttempt.items))).all()
    return {**level_of(sum(run(a)["xp"] for a in done)), "streak": streak(db, user.id)}
