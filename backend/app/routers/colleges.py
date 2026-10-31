from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import College, CollegeComparison, RankType, SavedCollege, StudentReview, User
from app.security import current_user
from app.services import catalog
from app.services.compare import PRIORITIES, CompareError, compare
from app.services.costs import estimate_cost
from app.services.predictor import PredictorInput, PredictorInputError, predict

router = APIRouter(prefix="/api", tags=["colleges"])


@router.get("/colleges")
def list_colleges(q: str | None = Query(None, max_length=100), state: str | None = None, course: str | None = None,
                  institution_type: str | None = None, page: int = Query(1, ge=1),
                  page_size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    return catalog.search_colleges(db, q=q, state=state, course=course, institution_type=institution_type,
                                   page=page, page_size=page_size)


@router.get("/colleges/facets")
def facets(db: Session = Depends(get_db)):
    rows = db.execute(select(College.state, College.institution_type)).all()
    return {"states": sorted({r[0] for r in rows}), "institution_types": sorted({r[1] for r in rows})}


def _college(db: Session, college_id: int) -> College:
    c = db.get(College, college_id)
    if c is None:
        raise HTTPException(404, "College not found")
    return c


@router.get("/colleges/{college_id}")
def college_detail(college_id: int, db: Session = Depends(get_db)):
    return catalog.college_detail(db, _college(db, college_id))


@router.get("/colleges/{college_id}/cost")
def college_cost(college_id: int, course: str = "MBBS", quota: str = "ALL", include_hostel: bool = True,
                 db: Session = Depends(get_db)):
    _college(db, college_id)
    return estimate_cost(db, college_id, course, quota, include_hostel).to_dict()


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    aspect_ratings: dict[str, int] = {}
    body: str = Field(min_length=30, max_length=3000)


@router.post("/colleges/{college_id}/reviews", status_code=202)
def submit_review(college_id: int, body: ReviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Reviews are held for moderation (abuse, defamation, personal data) before publishing."""
    _college(db, college_id)
    if any(not 1 <= v <= 5 for v in body.aspect_ratings.values()):
        raise HTTPException(422, "Aspect ratings must be between 1 and 5.")
    db.add(StudentReview(college_id=college_id, user_id=user.id, **body.model_dump(), status="pending"))
    db.commit()
    return {"status": "pending", "message": "Thanks! Your review will appear after moderation."}


# ------------------------------------------------------------------ saved colleges

@router.get("/saved-colleges")
def saved(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(SavedCollege).where(SavedCollege.user_id == user.id)).all()
    return [{"college": catalog.college_card(db, db.get(College, r.college_id)), "note": r.note} for r in rows]


@router.post("/saved-colleges/{college_id}", status_code=201)
def save(college_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _college(db, college_id)
    try:
        db.add(SavedCollege(user_id=user.id, college_id=college_id))
        db.commit()
    except IntegrityError:
        db.rollback()
    return {"ok": True}


@router.delete("/saved-colleges/{college_id}", status_code=204)
def unsave(college_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.query(SavedCollege).filter_by(user_id=user.id, college_id=college_id).delete()
    db.commit()


# ------------------------------------------------------------------ comparison

class CompareIn(BaseModel):
    college_ids: list[int] = Field(min_length=2, max_length=5)
    priorities: list[str] = ["cost", "cutoff", "hostel"]
    course_code: str = "MBBS"
    save: bool = False


@router.get("/compare/priorities")
def compare_priorities():
    return PRIORITIES


@router.post("/compare")
def compare_colleges(body: CompareIn, db: Session = Depends(get_db)):
    try:
        return compare(db, body.college_ids, body.priorities, body.course_code)
    except CompareError as e:
        raise HTTPException(422, str(e))


@router.post("/compare/save", status_code=201)
def save_comparison(body: CompareIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = CollegeComparison(user_id=user.id, college_ids=body.college_ids, priorities=body.priorities)
    db.add(c)
    db.commit()
    return {"id": c.id}


# ------------------------------------------------------------------ predictor

class PredictIn(BaseModel):
    course_code: str = "MBBS"
    exam_year: int = Field(ge=2015, le=2100)
    rank_type: RankType = RankType.official
    air: int | None = Field(None, ge=1)
    state_rank: int | None = Field(None, ge=1)
    air_low: int | None = Field(None, ge=1)
    air_high: int | None = Field(None, ge=1)
    category: str | None = None
    pwd: bool = False
    domicile_state: str | None = None
    quotas: list[str] = ["AIQ", "STATE"]
    preferred_states: list[str] = []
    institution_types: list[str] = []
    budget_max_annual: int | None = Field(None, ge=0)
    hostel_required: bool = False
    years_considered: int = Field(3, ge=1, le=10)


@router.post("/predict")
def run_predictor(body: PredictIn, db: Session = Depends(get_db)):
    """Anonymous use is allowed: inputs are not stored unless the student saves them to a profile."""
    try:
        return predict(db, PredictorInput(**body.model_dump()))
    except PredictorInputError as e:
        raise HTTPException(422, str(e))
