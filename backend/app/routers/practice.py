"""Practice tests in the NEET format, the syllabus with chapter progress, and the study plan."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    ChapterProgress, ExamAttempt, Question, StudentProfile, StudyPlan, StudyTask, SyllabusChapter, User,
)
from app.security import current_user
from app.services import exams, study_plan
from app.services.catalog import provenance

router = APIRouter(prefix="/api", tags=["practice"])


# ---------------------------------------------------------------- syllabus

@router.get("/syllabus")
def syllabus(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Question.chapter_id, func.count()).where(Question.review_status.in_(exams.SERVED))
                             .group_by(Question.chapter_id)).all())
    chapters = db.scalars(select(SyllabusChapter).order_by(SyllabusChapter.sort_order)).all()
    return {"source": provenance(chapters[0]) if chapters else None,
            "chapters": [{"id": c.id, "code": c.code, "subject": c.subject, "class_level": c.class_level, "name": c.name,
                          "est_hours": c.est_hours, "questions": counts.get(c.id, 0)} for c in chapters]}


@router.get("/syllabus/progress")
def my_progress(user: User = Depends(current_user), db: Session = Depends(get_db)):
    acc = exams.chapter_accuracy(db, user.id)
    rows = db.scalars(select(ChapterProgress).where(ChapterProgress.user_id == user.id)).all()
    ids = {r.chapter_id for r in rows} | set(acc)
    by = {r.chapter_id: r for r in rows}
    return {str(cid): {"status": by[cid].status if cid in by else None,
                       "confidence": by[cid].confidence if cid in by else None,
                       "tests": acc.get(cid)} for cid in ids}


class ProgressIn(BaseModel):
    status: Literal["not_started", "learning", "revised", "mastered"]
    confidence: int | None = Field(None, ge=1, le=5)


@router.put("/syllabus/progress/{chapter_id}")
def set_progress(chapter_id: int, body: ProgressIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if db.get(SyllabusChapter, chapter_id) is None:
        raise HTTPException(404, "Chapter not found")
    p = db.scalar(select(ChapterProgress).where(ChapterProgress.user_id == user.id,
                                                ChapterProgress.chapter_id == chapter_id))
    if p is None:
        p = ChapterProgress(user_id=user.id, chapter_id=chapter_id)
        db.add(p)
    p.status, p.confidence = body.status, body.confidence
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- practice tests

@router.get("/exams/pattern")
def pattern(db: Session = Depends(get_db)):
    return {"pattern": exams.NEET_PATTERN, "bank": exams.bank_counts(db)}


class AttemptIn(BaseModel):
    mode: Literal["full", "mini", "subject", "chapter", "weak"]
    subject: Literal["Physics", "Chemistry", "Botany", "Zoology", "Biology"] | None = None
    chapter_ids: list[int] | None = Field(None, max_length=10)
    count: int | None = Field(None, ge=5, le=90)
    strict_omr: bool = False


def _own_attempt(db: Session, user: User, attempt_id: int) -> ExamAttempt:
    a = db.get(ExamAttempt, attempt_id)
    if a is None or a.user_id != user.id:
        raise HTTPException(404, "Test not found")
    return a


@router.get("/exams/readiness")
def readiness(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Never-seen questions available to this student; starts writing more in the background when low."""
    return exams.readiness(db, user)


@router.post("/exams/attempts", status_code=201)
def create_paper(body: AttemptIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Prepares a paper of never-seen questions. 202 means fresh questions are still being written:
    the client polls /exams/readiness and tries again."""
    try:
        a = exams.create_attempt(db, user, body.mode, subject=body.subject, chapter_ids=body.chapter_ids,
                                 count=body.count, strict_omr=body.strict_omr)
    except exams.PaperNotReady as e:
        db.rollback()
        return JSONResponse({"status": "preparing", "detail": str(e), "needed": e.needed,
                             "generating": e.generating}, status_code=202 if e.generating else 422)
    except exams.ExamError as e:
        raise HTTPException(409 if "current test" in str(e) else 422, str(e))
    return exams.attempt_summary(a)


@router.post("/exams/attempts/{attempt_id}/start")
def open_booklet(attempt_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = _own_attempt(db, user, attempt_id)
    exams.start_attempt(db, a)
    return exams.attempt_view(db, a)


class ReportIn(BaseModel):
    reason: Literal["wrong_answer", "unclear", "out_of_syllabus", "typo", "other"]
    note: str | None = Field(None, max_length=1000)


@router.post("/exams/attempts/{attempt_id}/report/{position}")
def report(attempt_id: int, position: int, body: ReportIn, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    try:
        return exams.report_question(db, _own_attempt(db, user, attempt_id), position, user, body.reason, body.note)
    except exams.ExamError as e:
        raise HTTPException(409, str(e))


@router.get("/exams/attempts")
def list_attempts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ExamAttempt).where(ExamAttempt.user_id == user.id).order_by(ExamAttempt.id.desc()).limit(100)).all()
    for a in rows:
        exams.expire_if_due(db, a)
    return [exams.attempt_summary(a) for a in rows]


@router.get("/exams/attempts/{attempt_id}")
def get_attempt(attempt_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return exams.attempt_view(db, _own_attempt(db, user, attempt_id))


class AnswerIn(BaseModel):
    selected_index: int | None = Field(None, ge=0, le=3)
    marked_for_review: bool = False
    time_spent_delta: int = Field(0, ge=0, le=3600)


@router.put("/exams/attempts/{attempt_id}/answers/{position}")
def answer(attempt_id: int, position: int, body: AnswerIn, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    a = _own_attempt(db, user, attempt_id)
    try:
        item = exams.save_answer(db, a, position, selected_index=body.selected_index,
                                 marked_for_review=body.marked_for_review, time_spent_delta=body.time_spent_delta)
    except exams.ExamError as e:
        raise HTTPException(409, str(e))
    return {"position": item.position, "selected_index": item.selected_index,
            "marked_for_review": item.marked_for_review, "remaining_seconds": exams.remaining_seconds(a)}


@router.post("/exams/attempts/{attempt_id}/focus-lost")
def focus_lost(attempt_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = _own_attempt(db, user, attempt_id)
    if a.status == "in_progress":
        a.focus_lost_count += 1
        db.commit()
    return {"focus_lost_count": a.focus_lost_count}


@router.post("/exams/attempts/{attempt_id}/submit")
def submit_attempt(attempt_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = _own_attempt(db, user, attempt_id)
    try:
        exams.submit(db, a)
    except exams.ExamError as e:
        raise HTTPException(409, str(e))
    exams.readiness(db, user)  # refill this student's unseen pool in the background for next time
    return exams.attempt_view(db, a)


@router.get("/exams/performance")
def performance(user: User = Depends(current_user), db: Session = Depends(get_db)):
    acc = exams.chapter_accuracy(db, user.id)
    chapters = {c.id: c for c in db.scalars(select(SyllabusChapter).where(SyllabusChapter.id.in_(list(acc) or [0])))}
    rows = [{"chapter_id": cid, "chapter": chapters[cid].name, "subject": chapters[cid].subject, **s,
             "avg_seconds": round(s["seconds"] / s["seen"]) if s["seen"] else None}
            for cid, s in acc.items() if cid in chapters]
    rows.sort(key=lambda r: (r["accuracy"] if r["accuracy"] is not None else 101))
    return {"chapters": rows,
            "note": "Accuracy is over the questions you answered. Chapters with fewer than 5 answered questions "
                    "are not a reliable signal yet."}


# ---------------------------------------------------------------- study plan

@router.get("/study-plan")
def get_plan(user: User = Depends(current_user), db: Session = Depends(get_db)):
    plan = db.scalars(select(StudyPlan).where(StudyPlan.user_id == user.id).order_by(StudyPlan.id.desc())).first()
    if plan is None:
        raise HTTPException(404, "No study plan yet")
    return study_plan.plan_view(plan)


class PlanIn(BaseModel):
    current_class: Literal["11", "12", "dropper"] | None = None
    exam_date: date | None = None
    weekday_hours: float = Field(4, ge=0, le=12)
    weekend_hours: float = Field(7, ge=0, le=14)


@router.post("/study-plan", status_code=201)
def create_plan(body: PlanIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    cls = body.current_class or (profile.current_class if profile else None)
    if cls not in study_plan.CLASSES:
        cls = "dropper" if cls in ("graduated",) else None
    if cls is None:
        raise HTTPException(422, "Tell us your class (11, 12 or dropper) to build a plan.")
    today = date.today()
    if body.exam_date is not None and body.exam_date <= today:
        raise HTTPException(422, "The exam date must be in the future.")
    exam_date = body.exam_date or study_plan.estimated_exam_date(study_plan.default_exam_year(cls, today))
    try:
        plan = study_plan.build_plan(db, user, current_class=cls, start=today, exam_date=exam_date,
                                     exam_date_is_estimate=body.exam_date is None,
                                     weekday_hours=body.weekday_hours, weekend_hours=body.weekend_hours)
    except study_plan.PlanError as e:
        raise HTTPException(422, str(e))
    return study_plan.plan_view(plan)


class TaskPatch(BaseModel):
    status: Literal["todo", "done"]


@router.patch("/study-plan/tasks/{task_id}")
def patch_task(task_id: int, body: TaskPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(StudyTask, task_id)
    plan = db.get(StudyPlan, t.plan_id) if t else None
    if t is None or plan.user_id != user.id:
        raise HTTPException(404, "Task not found")
    t.status = body.status
    # Finishing study work moves the chapter forward on the syllabus tracker (never backwards).
    if body.status == "done" and t.chapter_id and t.kind in ("learn", "revise"):
        remaining = [x for x in plan.tasks if x.chapter_id == t.chapter_id and x.kind == "learn" and x.status != "done"
                     and x.id != t.id]
        target = "revised" if t.kind == "revise" else ("learning" if not remaining else None)
        if target:
            p = db.scalar(select(ChapterProgress).where(ChapterProgress.user_id == user.id,
                                                        ChapterProgress.chapter_id == t.chapter_id))
            if p is None:
                p = ChapterProgress(user_id=user.id, chapter_id=t.chapter_id, status="not_started")
                db.add(p)
            if study_plan.STATUS_RANK[target] > study_plan.STATUS_RANK[p.status]:
                p.status = target
    db.commit()
    return {"ok": True}
