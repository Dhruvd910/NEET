from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CounsellingAuthority, CounsellingRound, InfoArticle, PreferenceList, User
from app.routers.colleges import PredictIn
from app.security import current_user
from app.services.catalog import provenance
from app.services.predictor import FIT_ORDER, PredictorInput, PredictorInputError, predict

router = APIRouter(prefix="/api", tags=["counselling", "info"])

DRAFT_NOTICE = ("DRAFT for your own planning. It is not submitted anywhere. Review every choice and enter your "
                "final list yourself on the official counselling portal before the deadline.")


@router.get("/counselling/authorities")
def authorities(db: Session = Depends(get_db)):
    return [{"code": a.code, "name": a.name, "level": a.level, "state": a.state, "website": a.website,
             "quotas": a.quotas} for a in db.scalars(select(CounsellingAuthority).order_by(CounsellingAuthority.level, CounsellingAuthority.code))]


@router.get("/counselling/rounds")
def rounds(authority: str, exam_year: int, db: Session = Depends(get_db)):
    a = db.scalar(select(CounsellingAuthority).where(CounsellingAuthority.code == authority))
    if a is None:
        raise HTTPException(404, "Unknown authority")
    rows = db.scalars(select(CounsellingRound).where(CounsellingRound.authority_id == a.id,
                                                     CounsellingRound.exam_year == exam_year)
                      .order_by(CounsellingRound.round_number)).all()
    return {"authority": a.code, "exam_year": exam_year,
            "rounds": [{"round_number": r.round_number, "name": r.name, "registration_start": r.registration_start,
                        "registration_end": r.registration_end, "result_date": r.result_date, "notes": r.notes,
                        **provenance(r)} for r in rows],
            "note": None if rows else "No verified schedule stored for this year yet — check the authority's official website."}


@router.get("/info/{section}")
def info(section: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(InfoArticle).where(InfoArticle.section == section).order_by(InfoArticle.sort_order)).all()
    return [{"slug": r.slug, "title": r.title, "body": r.body, "exam_year": r.exam_year, **provenance(r)} for r in rows]


# ------------------------------------------------------------------ preference lists

class PrefItem(BaseModel):
    college_id: int
    college_name: str
    quota: str
    authority: str
    historical_fit: str | None = None
    note: str | None = Field(None, max_length=500)


class PrefListIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    authority_code: str
    exam_year: int
    course_code: str = "MBBS"
    items: list[PrefItem] = Field(default_factory=list, max_length=300)


class DraftIn(BaseModel):
    predict: PredictIn
    authority_code: str
    # Student's own priority order, e.g. ["government_first", "preferred_states", "lower_cost", "fit"]
    priorities: list[str] = ["government_first", "preferred_states", "lower_cost", "fit"]


def _pl_out(p: PreferenceList) -> dict:
    return {"id": p.id, "name": p.name, "authority_code": p.authority_code, "exam_year": p.exam_year,
            "course_code": p.course_code, "items": p.items, "status": p.status, "updated_at": p.updated_at,
            "notice": DRAFT_NOTICE}


@router.get("/preference-lists")
def list_prefs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_pl_out(p) for p in db.scalars(select(PreferenceList).where(PreferenceList.user_id == user.id))]


@router.post("/preference-lists", status_code=201)
def create_pref(body: PrefListIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = PreferenceList(user_id=user.id, **body.model_dump(exclude={"items"}),
                       items=[i.model_dump() for i in body.items], status="draft")
    db.add(p)
    db.commit()
    return _pl_out(p)


@router.put("/preference-lists/{pid}")
def update_pref(pid: int, body: PrefListIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(PreferenceList, pid)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "Not found")
    for k, v in body.model_dump(exclude={"items"}).items():
        setattr(p, k, v)
    p.items = [i.model_dump() for i in body.items]
    p.status = "draft"
    db.commit()
    return _pl_out(p)


@router.delete("/preference-lists/{pid}", status_code=204)
def delete_pref(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(PreferenceList, pid)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "Not found")
    db.delete(p)
    db.commit()


@router.post("/preference-lists/draft")
def draft_pref(body: DraftIn, db: Session = Depends(get_db)):
    """Suggest an ordering that follows the student's priorities. Historical fit is only one
    criterion (and only as important as the student ranks it). Nothing is saved or submitted."""
    try:
        res = predict(db, PredictorInput(**body.predict.model_dump()))
    except PredictorInputError as e:
        raise HTTPException(422, str(e))
    rows = [r for g in res["groups"].values() for r in g if r["counselling_authority"] == body.authority_code]
    prefs = set(body.predict.preferred_states)

    def key(r):
        k = []
        for p in body.priorities:
            if p == "government_first":
                k.append(0 if r["institution_type"] in ("government", "central") else 1)
            elif p == "preferred_states":
                k.append(0 if r["state"] in prefs else 1)
            elif p == "lower_cost":
                k.append(r["estimated_annual_cost_inr"] if r["estimated_annual_cost_inr"] is not None else 10**12)
            elif p == "fit":
                k.append(FIT_ORDER[r["historical_fit"]])
        return k

    rows.sort(key=key)
    items = []
    for r in rows:
        tradeoffs = []
        if r["historical_fit"] == "Ambitious":
            tradeoffs.append("ambitious historically — keep safer options below it too")
        if r["estimated_annual_cost_inr"] is None:
            tradeoffs.append("fees not verified")
        if r["is_demo"]:
            tradeoffs.append("DEMO data")
        items.append({"college_id": r["college_id"], "college_name": r["college_name"], "quota": r["quota"],
                      "authority": r["counselling_authority"], "historical_fit": r["historical_fit"],
                      "estimated_annual_cost_inr": r["estimated_annual_cost_inr"],
                      "note": "; ".join(tradeoffs) or None})
    return {
        "status": "draft", "notice": DRAFT_NOTICE, "authority_code": body.authority_code,
        "ordering_explained": (
            f"Ordered by your priorities: {', '.join(body.priorities)}. Colleges you would genuinely prefer should "
            "go above ones that are only easier to get; in most counselling systems listing a preferred college "
            "higher does not reduce your chance at the ones below it — confirm this in your authority's rules."),
        "items": items, "disclaimer": res["disclaimer"],
    }
