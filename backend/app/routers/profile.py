from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AcademicRecord, ExamProfile, RankType, RoadmapItem, StudentProfile, User
from app.security import current_user
from app.services.mock_analytics import analyse
from app.services.normalize import CATEGORY_MAP

router = APIRouter(prefix="/api", tags=["profile"])


class ProfileIn(BaseModel):
    display_name: str | None = Field(None, max_length=80)
    current_class: str | None = Field(None, pattern="^(11|12|dropper|graduated|other)$")
    academic_year: str | None = Field(None, max_length=9)
    state: str | None = None
    domicile_state: str | None = None
    class10_percentage: float | None = Field(None, ge=0, le=100)
    class12_status: str | None = None
    category: str | None = None
    sub_category: str | None = None
    pwd: bool | None = None
    preferred_course: str | None = None
    preferred_states: list[str] = []
    institution_preferences: list[str] = []
    budget_max_annual: int | None = Field(None, ge=0)
    hostel_required: bool | None = None
    language: str = "en"

    @model_validator(mode="after")
    def check_category(self):
        if self.category and self.category.upper() not in CATEGORY_MAP:
            raise ValueError(f"Unknown category. Use one of: {', '.join(sorted(set(CATEGORY_MAP.values())))}")
        return self


class ExamIn(BaseModel):
    exam_year: int = Field(ge=2015, le=2100)
    has_taken: bool = False
    score: int | None = Field(None, ge=-180, le=720)
    percentile: float | None = Field(None, ge=0, le=100)
    air: int | None = Field(None, ge=1)
    state_rank: int | None = Field(None, ge=1)
    rank_type: RankType = RankType.official
    estimated_rank_low: int | None = Field(None, ge=1)
    estimated_rank_high: int | None = Field(None, ge=1)
    estimate_basis: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def check(self):
        if self.rank_type == RankType.estimated:
            if self.air or self.state_rank:
                raise ValueError("Estimated ranks go in the estimated range fields, not the official AIR/state rank.")
            if self.estimated_rank_low and self.estimated_rank_high and self.estimated_rank_low > self.estimated_rank_high:
                raise ValueError("Estimated rank range: low must be ≤ high.")
        else:
            if self.estimated_rank_low or self.estimated_rank_high:
                raise ValueError("Use rank_type 'estimated' for an estimated range.")
        return self


class AcademicIn(BaseModel):
    level: str = Field(pattern="^(10|11|12)$")
    subject: str = Field(max_length=40)
    marks: float = Field(ge=0)
    max_marks: float = Field(gt=0)
    year: int | None = None


def _profile_dict(p: StudentProfile | None) -> dict | None:
    if p is None:
        return None
    return {c.name: getattr(p, c.name) for c in StudentProfile.__table__.columns if c.name not in ("id", "user_id")}


@router.get("/profile")
def get_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    exams = db.scalars(select(ExamProfile).where(ExamProfile.user_id == user.id).order_by(ExamProfile.exam_year)).all()
    acad = db.scalars(select(AcademicRecord).where(AcademicRecord.user_id == user.id)).all()
    return {
        "profile": _profile_dict(p),
        "exams": [{c.name: getattr(e, c.name) for c in ExamProfile.__table__.columns if c.name != "user_id"} for e in exams],
        "academics": [{c.name: getattr(a, c.name) for c in AcademicRecord.__table__.columns if c.name != "user_id"} for a in acad],
    }


@router.put("/profile")
def put_profile(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    if p is None:
        p = StudentProfile(user_id=user.id)
        db.add(p)
    data = body.model_dump()
    if data["category"]:
        data["category"] = CATEGORY_MAP[data["category"].upper()]
    for k, v in data.items():
        setattr(p, k, v)
    db.commit()
    return _profile_dict(p)


@router.put("/exam-profiles")
def put_exam(body: ExamIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.scalar(select(ExamProfile).where(ExamProfile.user_id == user.id, ExamProfile.exam_year == body.exam_year))
    if e is None:
        e = ExamProfile(user_id=user.id, exam_year=body.exam_year)
        db.add(e)
    for k, v in body.model_dump().items():
        setattr(e, k, v)
    db.commit()
    return {"ok": True, "id": e.id}


@router.post("/academic-records", status_code=201)
def add_academic(body: AcademicIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.marks > body.max_marks:
        raise HTTPException(422, "Marks cannot exceed maximum marks.")
    r = AcademicRecord(user_id=user.id, **body.model_dump())
    db.add(r)
    db.commit()
    return {"id": r.id}


@router.delete("/academic-records/{rid}", status_code=204)
def del_academic(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(AcademicRecord, rid)
    if r is None or r.user_id != user.id:
        raise HTTPException(404, "Not found")
    db.delete(r)
    db.commit()


# ------------------------------------------------------------------ roadmap

class RoadmapPatch(BaseModel):
    status: str = Field(pattern="^(todo|doing|done)$")


@router.get("/roadmap")
def get_roadmap(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(RoadmapItem).where(RoadmapItem.user_id == user.id).order_by(RoadmapItem.id)).all()
    return [{"id": i.id, "title": i.title, "detail": i.detail, "kind": i.kind, "status": i.status,
             "due_date": i.due_date} for i in items]


@router.post("/roadmap/generate")
def generate_roadmap(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Personalised milestones. Official dates change every year, so we never hard-code them:
    admission milestones point to the authority whose notice sets the date."""
    from app.models import MockTest
    p = db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    exam = db.scalars(select(ExamProfile).where(ExamProfile.user_id == user.id)
                      .order_by(ExamProfile.exam_year.desc())).first()
    tests = db.scalars(select(MockTest).where(MockTest.user_id == user.id)).all()
    stats = analyse(list(tests))

    items: list[tuple[str, str, str]] = []
    taken = bool(exam and exam.has_taken)
    if not taken:
        items += [
            ("study", "Map the official NEET-UG syllabus", "Download the syllabus from the current NTA information bulletin and tick off chapters by subject."),
            ("study", "Take a full-length timed mock every 1–2 weeks", "Log each one on the Mock Tests page to track trends."),
        ]
        for pr in stats["priorities"][:4]:
            items.append(("study", "Revision priority", pr))
        if stats["count"] < 3:
            items.append(("study", "Log at least 3 mock tests", "Trends and estimates need a few data points."))
        items += [
            ("admission", "Watch for the NEET-UG application window", "Dates are announced by NTA each year — check neet.nta.nic.in and the Information Bulletin. We will not guess dates."),
            ("admission", "Prepare documents for the application", "Photo, signature, ID, class 10/12 documents and category/PwD certificates if applicable — follow the current bulletin's list."),
        ]
    else:
        has_rank = bool(exam.air or exam.state_rank)
        items += [
            ("admission", "Enter your official AIR / state rank" if not has_rank else "Review your college matches",
             "Use the College Predictor to see historical cutoff matches for your rank."),
            ("counselling", "Register for MCC counselling (AIQ / deemed / central)", "Check mcc.nic.in for the schedule announced this year."),
            ("counselling", f"Register for state counselling{' in ' + p.domicile_state if p and p.domicile_state else ''}",
             "Your state counselling authority publishes its own schedule and rules."),
            ("counselling", "Build a draft preference list", "Order colleges by YOUR priorities; review before entering it on the official portal."),
            ("counselling", "Collect counselling documents", "See the Counselling page checklist and the official notice for the authoritative list."),
        ]
    db.query(RoadmapItem).filter(RoadmapItem.user_id == user.id, RoadmapItem.generated.is_(True),
                                 RoadmapItem.status != "done").delete()
    for kind, title, detail in items:
        db.add(RoadmapItem(user_id=user.id, kind=kind, title=title, detail=detail, generated=True))
    db.commit()
    return get_roadmap(user, db)


@router.patch("/roadmap/{item_id}")
def patch_roadmap(item_id: int, body: RoadmapPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    i = db.get(RoadmapItem, item_id)
    if i is None or i.user_id != user.id:
        raise HTTPException(404, "Not found")
    i.status = body.status
    db.commit()
    return {"ok": True}
