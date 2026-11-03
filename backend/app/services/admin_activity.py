"""What admins see about students: site-wide "vitals" (daily trends), a live activity feed, and one student's file.

Kept deliberately narrow: no chat contents (counts only), no category or disability status, and the NEET rank only
as "added / not added". Opening a student's file is written to the audit log.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ChapterProgress, ChatMessage, ChatSession, College, ExamAttempt, ExamProfile, LoginEvent, MockTest, SavedCollege,
    StudentProfile, StudyPlan, User,
)

IST = ZoneInfo("Asia/Kolkata")


def _ist(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(IST)


def _days(n: int) -> list[date]:
    today = datetime.now(IST).date()
    return [today - timedelta(days=i) for i in range(n - 1, -1, -1)]


def _per_day(stamps, days: list[date]) -> list[int]:
    counts = Counter(_ist(s).date() for s in stamps if s is not None)
    return [counts.get(d, 0) for d in days]


def spark(values: list[int], width: int = 132, height: int = 34) -> str:
    """SVG polyline points for a small trend line (drawn like a monitor trace on the vitals cards)."""
    top = max(values) or 1
    step = width / max(1, len(values) - 1)
    return " ".join(f"{i * step:.1f},{height - 3 - (v / top) * (height - 8):.1f}" for i, v in enumerate(values))


def vitals(db: Session, days: int = 14) -> dict:
    """Site-wide numbers with a 14-day trend each."""
    span = _days(days)
    since = datetime.combine(span[0], datetime.min.time(), IST).astimezone(timezone.utc)
    week = datetime.now(timezone.utc) - timedelta(days=7)
    day = datetime.now(timezone.utc) - timedelta(days=1)

    def stamps(col, *where):
        return db.scalars(select(col).where(col >= since, *where)).all()

    signups = _per_day(stamps(User.created_at), span)
    signins = _per_day(stamps(LoginEvent.at), span)
    tests = _per_day(stamps(ExamAttempt.submitted_at), span)
    chats = _per_day(stamps(ChatSession.created_at), span)
    active = lambda after: db.scalar(select(func.count(func.distinct(LoginEvent.user_id))).where(LoginEvent.at >= after)) or 0  # noqa: E731
    total = db.scalar(select(func.count(User.id))) or 0
    return {
        "labels": [f"{d.day} {d:%b}" for d in span],
        "cards": [
            {"key": "students", "label": "Students", "value": total, "sub": f"+{sum(signups[-7:])} this week",
             "series": signups, "icon": "BadgeId", "tone": "teal"},
            {"key": "active", "label": "Active today", "value": active(day), "sub": f"{active(week)} this week",
             "series": signins, "icon": "HeartPulse", "tone": "rose"},
            {"key": "signins", "label": "Sign-ins today", "value": signins[-1], "sub": f"{sum(signins[-7:])} this week",
             "series": signins, "icon": "Stethoscope", "tone": "sky"},
            {"key": "tests", "label": "Tests submitted", "value": sum(tests[-7:]), "sub": "last 7 days",
             "series": tests, "icon": "Clipboard", "tone": "violet"},
            {"key": "chats", "label": "Assistant chats", "value": sum(chats[-7:]), "sub": "last 7 days",
             "series": chats, "icon": "Microscope", "tone": "amber"},
        ],
    }


def activity_feed(db: Session, limit: int = 25, user_id: int | None = None) -> list[dict]:
    """Recent events across the site (or for one student), newest first."""
    def q(stmt):
        return db.execute(stmt.where(User.id == user_id) if user_id else stmt).all()

    events = []
    for u in q(select(User).order_by(User.created_at.desc()).limit(limit)):
        u = u[0]
        events.append({"at": u.created_at, "user": u, "kind": "signup", "text": "joined NEET Compass"})
    for e, u in q(select(LoginEvent, User).join(User, User.id == LoginEvent.user_id).order_by(LoginEvent.at.desc()).limit(limit)):
        how = {"google": "with Google", "phone": "with a phone code", "password": "with a password",
               "admin": "to the admin console", "signup": "for the first time"}.get(e.method, "")
        events.append({"at": e.at, "user": u, "kind": "signin", "text": f"signed in {how}".strip()})
    for a, u in q(select(ExamAttempt, User).join(User, User.id == ExamAttempt.user_id)
                  .where(ExamAttempt.submitted_at.is_not(None)).order_by(ExamAttempt.submitted_at.desc()).limit(limit)):
        pct = round(100 * (a.score or 0) / a.max_score) if a.max_score else 0
        events.append({"at": a.submitted_at, "user": u, "kind": "test",
                       "text": f"finished {a.title}: {a.score}/{a.max_score} ({pct}%)"})
    for c, u in q(select(ChatSession, User).join(User, User.id == ChatSession.user_id)
                  .order_by(ChatSession.created_at.desc()).limit(limit)):
        events.append({"at": c.created_at, "user": u, "kind": "chat", "text": "asked the assistant"})
    for m, u in q(select(MockTest, User).join(User, User.id == MockTest.user_id).order_by(MockTest.id.desc()).limit(limit)):
        events.append({"at": datetime.combine(m.test_date, datetime.min.time(), timezone.utc), "user": u, "kind": "mock",
                       "text": f"logged a mock test: {m.total_score:g}/{m.max_score:g}"})
    events.sort(key=lambda e: _ist(e["at"]), reverse=True)
    return events[:limit]


def triage(user: User) -> tuple[str, str]:
    """How recently a student was around, as a ward-style status: (label, tone)."""
    seen = _ist(user.last_login_at or user.created_at)
    days = (datetime.now(IST) - seen).days if seen else 999
    if days < 1:
        return "Active today", "emerald"
    if days < 7:
        return "This week", "sky"
    if days < 30:
        return "This month", "amber"
    return "Inactive", "slate"


def student_file(db: Session, user: User) -> dict:
    """One student's activity, for the admin's case-file page."""
    prof = db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    exam = db.scalars(select(ExamProfile).where(ExamProfile.user_id == user.id).order_by(ExamProfile.exam_year.desc())).first()
    attempts = db.scalars(select(ExamAttempt).where(ExamAttempt.user_id == user.id).order_by(ExamAttempt.started_at.desc())).all()
    done = [a for a in attempts if a.status == "submitted" and a.max_score]
    pcts = [round(100 * (a.score or 0) / a.max_score) for a in done]
    mocks = db.scalars(select(MockTest).where(MockTest.user_id == user.id).order_by(MockTest.test_date.desc())).all()
    plan = db.scalars(select(StudyPlan).where(StudyPlan.user_id == user.id).order_by(StudyPlan.id.desc())).first()
    tasks = [t for t in (plan.tasks if plan else []) if t.kind != "board"]
    progress = Counter(db.scalars(select(ChapterProgress.status).where(ChapterProgress.user_id == user.id)))
    saved = db.scalars(select(College.name).join(SavedCollege, SavedCollege.college_id == College.id)
                       .where(SavedCollege.user_id == user.id).order_by(SavedCollege.created_at.desc())).all()
    chats = db.scalar(select(func.count(ChatSession.id)).where(ChatSession.user_id == user.id)) or 0
    questions = db.scalar(select(func.count(ChatMessage.id)).join(ChatSession).where(
        ChatSession.user_id == user.id, ChatMessage.role == "user")) or 0
    signins = db.scalars(select(LoginEvent).where(LoginEvent.user_id == user.id).order_by(LoginEvent.at.desc()).limit(20)).all()
    span = _days(30)
    since = datetime.combine(span[0], datetime.min.time(), IST).astimezone(timezone.utc)
    active_days = set(_ist(e.at).date() for e in db.scalars(select(LoginEvent).where(
        LoginEvent.user_id == user.id, LoginEvent.at >= since)))
    active_days |= set(_ist(a.started_at).date() for a in attempts if _ist(a.started_at) and _ist(a.started_at).date() >= span[0])
    return {
        "user": user, "triage": triage(user),
        "methods": [m for m, on in (("Google", user.google_sub), ("Phone", user.tekurious_user_id),
                                    ("Password", user.password_hash.startswith("scrypt$"))) if on],
        "profile": {"Class": {"11": "Class 11", "12": "Class 12", "dropper": "Dropper", "graduated": "Finished class 12"}
                    .get(prof.current_class, prof.current_class) if prof and prof.current_class else None,
                    "State": prof.state if prof else None, "Target course": prof.preferred_course if prof else None,
                    "NEET rank": ("Added" if exam and (exam.air or exam.estimated_rank_low) else "Not added")},
        "practice": {"taken": len(done), "in_progress": sum(a.status != "submitted" for a in attempts),
                     "average": round(sum(pcts) / len(pcts)) if pcts else None, "best": max(pcts) if pcts else None,
                     "latest": pcts[0] if pcts else None, "trend": list(reversed(pcts[:12])),
                     "rows": [{"a": a, "pct": round(100 * (a.score or 0) / a.max_score) if a.status == "submitted" and a.max_score else None}
                              for a in attempts[:12]]},
        "mocks": {"count": len(mocks), "latest": (round(100 * mocks[0].total_score / mocks[0].max_score) if mocks else None)},
        "plan": {"exists": plan is not None, "class": plan.current_class if plan else None,
                 "exam_date": plan.exam_date if plan else None, "done": sum(t.status == "done" for t in tasks),
                 "total": len(tasks)},
        "syllabus": {"confident": progress.get("mastered", 0), "revised": progress.get("revised", 0),
                     "learning": progress.get("learning", 0)},
        "saved": saved[:8], "saved_count": len(saved),
        "assistant": {"chats": chats, "questions": questions},
        "signins": signins,
        "calendar": [{"day": d, "active": d in active_days} for d in span],
        "timeline": activity_feed(db, limit=30, user_id=user.id),
    }
