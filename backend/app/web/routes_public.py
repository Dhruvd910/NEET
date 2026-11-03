"""Public pages: home, college search and detail, predictor, NEET info and careers."""
from __future__ import annotations

from datetime import date
from math import ceil
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.models import College, CollegeCourse, ExamProfile, SavedCollege, StudentProfile, StudentReview
from app.routers import colleges as colleges_api
from app.routers import counselling as counselling_api
from app.routers.colleges import PredictIn
from app.services import catalog
from app.services.predictor import PredictorInput, PredictorInputError, predict
from app.web.core import Page, page, student_page

router = APIRouter(include_in_schema=False)

TABS = [("overview", "Overview"), ("admission", "Admission"), ("fees", "Fees & cost"), ("hostel", "Hostel"),
        ("academics", "Academics"), ("outcomes", "Outcomes"), ("campus", "Campus life"), ("around", "Around campus")]
NEARBY_ORDER = ["Getting around", "Health & safety", "Food", "Stay (outside campus)", "Daily needs", "Study & leisure", "Other"]


def saved_ids(p: Page) -> set[int]:
    if p.user is None:
        return set()
    return set(p.db.scalars(select(SavedCollege.college_id).where(SavedCollege.user_id == p.user.id)))


def _college(p: Page, college_id: int) -> College:
    c = p.db.get(College, college_id)
    if c is None:
        raise HTTPException(404, "College not found")
    return c


@router.get("/", response_class=HTMLResponse)
def home(p: Page = Depends(page)):
    year = p.db.scalar(select(func.max(CollegeCourse.academic_year)))
    stats = {"colleges": p.db.scalar(select(func.count(College.id)).where(College.is_demo.is_(False))) or 0,
             "seats": p.db.scalar(select(func.sum(CollegeCourse.approved_intake)).join(College)
                                  .where(College.is_demo.is_(False), CollegeCourse.academic_year == year)) or 0,
             "year": year or "—"}
    return p.render("home.html", stats=stats)


@router.get("/colleges", response_class=HTMLResponse)
def colleges(p: Page = Depends(page), q: str | None = Query(None, max_length=100), state: str | None = None,
             course: str | None = None, institution_type: str | None = None, page_no: int = Query(1, ge=1, alias="page")):
    f = {"q": q or None, "state": state or None, "course": course or None, "institution_type": institution_type or None}
    data = catalog.search_colleges(p.db, **f, page=page_no, page_size=20)
    return p.render("colleges/list.html", f=f, facets=colleges_api.facets(p.db), data=data, saved=saved_ids(p),
                    pages=max(1, ceil(data["total"] / data["page_size"])),
                    query_without_page=urlencode({k: v for k, v in f.items() if v}))


@router.get("/colleges/{college_id}", response_class=HTMLResponse)
def college(college_id: int, p: Page = Depends(page), tab: str = "overview", route: str | None = None,
            cat: str | None = None, ncat: str = "All"):
    d = catalog.college_detail(p.db, _college(p, college_id))
    tab = tab if tab in dict(TABS) else "overview"
    ctx = {}
    if tab == "admission":
        # Cutoffs are only comparable within one course · authority · quota route and one category.
        key = lambda c: f"{c['course']} · {c['authority']} · {c['quota']}"  # noqa: E731
        cutoffs = d["admission"]["cutoffs"]
        routes = list(dict.fromkeys(key(c) for c in cutoffs))
        route = route if route in routes else (routes[0] if routes else None)
        cats = list(dict.fromkeys(c["category"] for c in cutoffs if key(c) == route))
        cat = cat if cat in cats else (cats[0] if cats else None)
        ctx = {"routes": routes, "route": route, "cats": cats, "cat": cat,
               "cutoff_rows": [c for c in cutoffs if key(c) == route and c["category"] == cat]}
    elif tab == "around":
        places = d["nearby"]
        groups = [(g, sorted((x for x in places if x["category"] == g), key=lambda x: x["distance_km"] or 999))
                  for g in NEARBY_ORDER]
        groups = [(g, ps) for g, ps in groups if ps]
        ctx = {"groups": groups, "ncat": ncat if ncat in dict(groups) else "All",
               "attribution": next((x["attribution"] for x in places if x["attribution"]), None),
               "map_places": [{"lat": x["latitude"], "lon": x["longitude"], "name": x["name"], "km": x["distance_km"],
                               "kind": x["kind"]} for x in places if x["latitude"] is not None]}
    return p.render("colleges/detail.html", d=d, tab=tab, TABS=TABS, saved=college_id in saved_ids(p), **ctx)


@router.post("/saved/{college_id}/toggle", response_class=HTMLResponse)
def toggle_saved(college_id: int, p: Page = Depends(student_page)):
    _college(p, college_id)
    q = p.db.query(SavedCollege).filter_by(user_id=p.user.id, college_id=college_id)
    now_saved = q.first() is None
    if now_saved:
        try:
            p.db.add(SavedCollege(user_id=p.user.id, college_id=college_id))
            p.db.commit()
        except IntegrityError:
            p.db.rollback()
    else:
        q.delete()
        p.db.commit()
    label = "★ Saved" if now_saved else "☆ Save"
    return HTMLResponse(f'<button class="btn-secondary" hx-post="/saved/{college_id}/toggle" hx-swap="outerHTML" '
                        f'aria-pressed="{str(now_saved).lower()}">{label}</button>')


@router.post("/colleges/{college_id}/reviews", response_class=HTMLResponse)
async def submit_review(college_id: int, request: Request, p: Page = Depends(student_page)):
    _college(p, college_id)
    form = await request.form()
    try:
        body = colleges_api.ReviewIn(rating=form.get("rating") or 0, body=(form.get("body") or "").strip())
    except ValidationError:
        return HTMLResponse('<p class="rounded-lg bg-red-50 p-3 text-sm text-red-800">Please pick a rating and write '
                            'at least 30 characters.</p>', status_code=422)
    p.db.add(StudentReview(college_id=college_id, user_id=p.user.id, **body.model_dump(), status="pending"))
    p.db.commit()
    return HTMLResponse('<p class="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">Thanks! Your review will '
                        'appear after moderation.</p>')


# ------------------------------------------------------------------ predictor

def _default_form() -> dict:
    return {"course_code": "MBBS", "exam_year": date.today().year, "rank_type": "official", "air": None,
            "state_rank": None, "air_low": None, "air_high": None, "category": "", "domicile_state": "",
            "budget_max_annual": None, "quotas": ["AIQ", "STATE"], "institution_types": [], "pwd": False,
            "hostel_required": False}


@router.get("/predictor", response_class=HTMLResponse)
def predictor_page(p: Page = Depends(page)):
    f, prefilled = _default_form(), False
    if p.user is not None:
        prof = p.db.scalar(select(StudentProfile).where(StudentProfile.user_id == p.user.id))
        exam = p.db.scalars(select(ExamProfile).where(ExamProfile.user_id == p.user.id)
                            .order_by(ExamProfile.exam_year.desc())).first()
        if prof:
            f.update(course_code=prof.preferred_course or "MBBS", category=prof.category or "", pwd=bool(prof.pwd),
                     domicile_state=prof.domicile_state or "", budget_max_annual=prof.budget_max_annual,
                     hostel_required=bool(prof.hostel_required))
        if exam:
            f.update(exam_year=exam.exam_year, rank_type=exam.rank_type.value, air=exam.air, state_rank=exam.state_rank,
                     air_low=exam.estimated_rank_low, air_high=exam.estimated_rank_high)
        prefilled = bool(prof or exam)
    return p.render("predictor.html", f=f, prefilled=prefilled, res=None, error=None, saved=saved_ids(p))


@router.post("/predictor", response_class=HTMLResponse)
async def predictor_run(request: Request, p: Page = Depends(page)):
    form = await request.form()
    num = lambda k: int(form[k]) if (form.get(k) or "").strip().isdigit() else None  # noqa: E731
    estimated = form.get("rank_type") == "estimated"
    f = {**_default_form(), "course_code": form.get("course_code") or "MBBS", "exam_year": num("exam_year") or 0,
         "rank_type": "estimated" if estimated else "official",
         "air": None if estimated else num("air"), "state_rank": None if estimated else num("state_rank"),
         "air_low": num("air_low") if estimated else None, "air_high": num("air_high") if estimated else None,
         "category": form.get("category") or "", "domicile_state": form.get("domicile_state") or "",
         "budget_max_annual": num("budget_max_annual"), "quotas": form.getlist("quotas"),
         "institution_types": form.getlist("institution_types"), "pwd": bool(form.get("pwd")),
         "hostel_required": bool(form.get("hostel_required"))}
    res, error = None, None
    try:
        body = PredictIn(**{**f, "category": f["category"] or None, "domicile_state": f["domicile_state"] or None})
        res = predict(p.db, PredictorInput(**body.model_dump()))
    except ValidationError as e:
        error = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
    except PredictorInputError as e:
        error = str(e)
    return p.render("predictor.html", f=f, prefilled=False, res=res, error=error, saved=saved_ids(p),
                    status_code=200 if res else 422)


# ------------------------------------------------------------------ information pages

INFO = {
    "neet": dict(title="NEET-UG information hub", icon_name="Microscope", eyebrow="Know your exam", tone="warn",
                 intro="The exam, eligibility, applications and results — each topic linked to its official source.",
                 warning="Dates, patterns and rules change every year. Items marked “Pending verification” have not yet "
                         "been checked against this year's official Information Bulletin. The official NTA website is "
                         "always the final authority."),
    "careers": dict(title="Other healthcare & life-science pathways", icon_name="Dna", eyebrow="Beyond MBBS", tone="info",
                    intro="MBBS is one of many ways to build a career in health. These pathways have their own entrance "
                          "routes and rules.",
                    warning="Not every pathway uses NEET or NEET counselling. Check each course's current admission "
                            "notice before deciding."),
}


@router.get("/neet", response_class=HTMLResponse)
def neet_info(p: Page = Depends(page)):
    return p.render("info.html", articles=counselling_api.info("neet", p.db), **INFO["neet"])


@router.get("/careers", response_class=HTMLResponse)
def careers(p: Page = Depends(page)):
    return p.render("info.html", articles=counselling_api.info("careers", p.db), **INFO["careers"])


# ------------------------------------------------------------------ legal pages

LEGAL_UPDATED = "3 Nov 2026"


@router.get("/privacy", response_class=HTMLResponse)
def privacy(p: Page = Depends(page)):
    return p.render("legal/privacy.html", updated=LEGAL_UPDATED, contact=get_settings().contact_email)


@router.get("/terms", response_class=HTMLResponse)
def terms(p: Page = Depends(page)):
    return p.render("legal/terms.html", updated=LEGAL_UPDATED, contact=get_settings().contact_email)
