"""Signed-in student pages: dashboard, profile, study plan and the mock-test log.

Each handler reuses the JSON API function (passing the signed-in user and session), so business rules and
validation live in one place. Form posts come from HTMX; the response re-renders the page and HTMX swaps
the region named in the template's hx-select.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from app.routers import colleges as colleges_api
from app.routers import mock_tests as mock_api
from app.routers import practice as practice_api
from app.routers import profile as profile_api
from app.web.core import Page, fmt_date, student_page

router = APIRouter(include_in_schema=False)


def error_text(e: Exception) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(x["msg"].removeprefix("Value error, ") for x in e.errors())
    if isinstance(e, HTTPException):
        return str(e.detail)
    return str(e)


def _blank(form, k: str) -> str | None:
    v = (form.get(k) or "").strip()
    return v or None


def _number(form, k: str, cast=float):
    v = _blank(form, k)
    try:
        return cast(v) if v is not None else None
    except ValueError:
        return None


# ------------------------------------------------------------------ dashboard

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(p: Page = Depends(student_page)):
    prof = profile_api.get_profile(p.user, p.db)
    return p.render("student/dashboard.html", profile=prof["profile"], exam=(prof["exams"] or [None])[-1],
                    roadmap=profile_api.get_roadmap(p.user, p.db), mocks=mock_api.analytics(p.user, p.db),
                    saved=colleges_api.saved(p.user, p.db))


@router.post("/roadmap/generate", response_class=HTMLResponse)
def roadmap_generate(p: Page = Depends(student_page)):
    profile_api.generate_roadmap(p.user, p.db)
    return dashboard(p)


@router.post("/roadmap/{item_id}", response_class=HTMLResponse)
async def roadmap_status(item_id: int, request: Request, p: Page = Depends(student_page)):
    form = await request.form()
    profile_api.patch_roadmap(item_id, profile_api.RoadmapPatch(status=form.get("status") or "todo"), p.user, p.db)
    return dashboard(p)


# ------------------------------------------------------------------ profile

def _profile_page(p: Page, msg: str | None = None, error: str | None = None, status_code: int = 200):
    prof = profile_api.get_profile(p.user, p.db)
    return p.render("student/profile.html", status_code=status_code, msg=msg, error=error,
                    p_=prof["profile"] or {"preferred_states": [], "institution_preferences": []},
                    exam=(prof["exams"] or [None])[-1], this_year=date.today().year)


@router.get("/profile", response_class=HTMLResponse)
def profile(p: Page = Depends(student_page)):
    return _profile_page(p)


@router.post("/profile", response_class=HTMLResponse)
async def profile_save(request: Request, p: Page = Depends(student_page)):
    f = await request.form()
    try:
        body = profile_api.ProfileIn(
            display_name=_blank(f, "display_name"), current_class=_blank(f, "current_class"),
            academic_year=_blank(f, "academic_year"), state=_blank(f, "state"), domicile_state=_blank(f, "domicile_state"),
            class10_percentage=_number(f, "class10_percentage"), category=_blank(f, "category"), pwd=bool(f.get("pwd")),
            preferred_course=_blank(f, "preferred_course"), preferred_states=f.getlist("preferred_states"),
            institution_preferences=f.getlist("institution_preferences"),
            budget_max_annual=_number(f, "budget_max_annual", int), hostel_required=bool(f.get("hostel_required")))
        profile_api.put_profile(body, p.user, p.db)
    except (ValidationError, HTTPException) as e:
        return _profile_page(p, error=error_text(e), status_code=422)
    return _profile_page(p, msg="Profile saved.")


@router.post("/profile/exam", response_class=HTMLResponse)
async def exam_save(request: Request, p: Page = Depends(student_page)):
    f = await request.form()
    taken = f.get("taken") == "yes"
    estimated = taken and f.get("rank_type") == "estimated"
    official = taken and not estimated
    try:
        body = profile_api.ExamIn(
            exam_year=_number(f, "exam_year", int) or 0, has_taken=taken,
            score=_number(f, "score", int) if taken else None, percentile=_number(f, "percentile") if taken else None,
            rank_type="estimated" if estimated else "official",
            air=_number(f, "air", int) if official else None, state_rank=_number(f, "state_rank", int) if official else None,
            estimated_rank_low=_number(f, "estimated_rank_low", int) if estimated else None,
            estimated_rank_high=_number(f, "estimated_rank_high", int) if estimated else None)
        profile_api.put_exam(body, p.user, p.db)
    except (ValidationError, HTTPException) as e:
        return _profile_page(p, error=error_text(e), status_code=422)
    return _profile_page(p, msg="Exam details saved.")


# ------------------------------------------------------------------ study plan

def _plan_page(p: Page, subject: str = "Physics", error: str | None = None, status_code: int = 200, show_all=False):
    try:
        plan = practice_api.get_plan(p.user, p.db)
    except HTTPException:
        plan = None
    prof = profile_api.get_profile(p.user, p.db)["profile"]
    chapters = practice_api.syllabus(p.db)["chapters"]
    progress = practice_api.my_progress(p.user, p.db)
    ctx = {"plan": plan, "error": error, "subject": subject if subject in ("Physics", "Chemistry", "Botany", "Zoology") else "Physics",
           "chapters": chapters, "progress": progress, "show_all": show_all,
           "default_class": (plan or {}).get("current_class") or (prof or {}).get("current_class") or "12"}
    if plan:
        current = next((w for w in plan["weeks"] if w["week_index"] == plan["current_week"]), plan["weeks"][0] if plan["weeks"] else None)
        ctx.update(current=current,
                   upcoming=[w for w in plan["weeks"] if w["week_index"] > (current["week_index"] if current else -1)],
                   pct=round(100 * plan["progress"]["done"] / plan["progress"]["total"]) if plan["progress"]["total"] else 0)
    return p.render("student/study_plan.html", status_code=status_code, **ctx)


@router.get("/study-plan", response_class=HTMLResponse)
def study_plan(p: Page = Depends(student_page), subject: str = "Physics", all: bool = False):  # noqa: A002
    return _plan_page(p, subject, show_all=all)


@router.post("/study-plan", response_class=HTMLResponse)
async def study_plan_build(request: Request, p: Page = Depends(student_page)):
    f = await request.form()
    try:
        body = practice_api.PlanIn(current_class=_blank(f, "current_class"), exam_date=_blank(f, "exam_date"),
                                   weekday_hours=_number(f, "weekday_hours") or 0, weekend_hours=_number(f, "weekend_hours") or 0)
        practice_api.create_plan(body, p.user, p.db)
    except (ValidationError, HTTPException) as e:
        return _plan_page(p, error=error_text(e), status_code=422)
    return _plan_page(p)


@router.post("/study-plan/tasks/{task_id}", response_class=HTMLResponse)
async def study_task(task_id: int, request: Request, p: Page = Depends(student_page)):
    f = await request.form()
    practice_api.patch_task(task_id, practice_api.TaskPatch(status="done" if f.get("done") else "todo"), p.user, p.db)
    return _plan_page(p, f.get("subject") or "Physics", show_all=bool(f.get("all")))


@router.post("/syllabus/{chapter_id}", response_class=HTMLResponse)
async def syllabus_status(chapter_id: int, request: Request, p: Page = Depends(student_page)):
    f = await request.form()
    practice_api.set_progress(chapter_id, practice_api.ProgressIn(status=f.get("status") or "not_started"), p.user, p.db)
    return _plan_page(p, f.get("subject") or "Physics")


# ------------------------------------------------------------------ mock-test log

MOCK_SUBJECTS = [("Physics", 180), ("Chemistry", 180), ("Biology", 360)]
SERIES_COLOR = {"Total": "#0f766e", "Physics": "#4f46e5", "Chemistry": "#c2410c", "Biology": "#15803d"}


def score_chart(history: list[dict], width: int = 640, height: int = 260) -> dict:
    """Line chart (percent of maximum over time) laid out in Python and drawn as inline SVG by the template."""
    left, right, top, bottom = 36, 12, 12, 30
    n = len(history)
    x = lambda i: left + (width - left - right) * (i / (n - 1) if n > 1 else 0.5)  # noqa: E731
    y = lambda v: top + (height - top - bottom) * (1 - v / 100)  # noqa: E731
    series = []
    for name in SERIES_COLOR:
        pts = [(x(i), y(h["percent"] if name == "Total" else h["subjects"][name]), h["percent"] if name == "Total"
                else h["subjects"][name]) for i, h in enumerate(history) if name == "Total" or name in h["subjects"]]
        if pts:
            series.append({"name": name, "color": SERIES_COLOR[name], "dashed": name != "Total",
                           "points": " ".join(f"{a:.1f},{b:.1f}" for a, b, _ in pts),
                           "dots": [{"x": a, "y": b, "v": v} for a, b, v in pts]})
    step = max(1, n // 6)  # at most ~6 date labels
    return {"width": width, "height": height, "series": series,
            "grid": [{"y": y(v), "label": v} for v in (0, 25, 50, 75, 100)], "left": left, "right": width - right,
            "xlabels": [{"x": x(i), "label": fmt_date(h["test_date"])} for i, h in enumerate(history) if i % step == 0 or i == n - 1],
            "baseline": height - bottom}


def _mock_page(p: Page, error: str | None = None, status_code: int = 200, open_form: bool = False):
    data = mock_api.analytics(p.user, p.db)
    return p.render("student/mock_tests.html", status_code=status_code, data=data, error=error, open_form=open_form,
                    chart=score_chart(data["history"]) if data["count"] else None, SUBJECTS=MOCK_SUBJECTS,
                    today=date.today().isoformat())


@router.get("/mock-tests", response_class=HTMLResponse)
def mock_tests(p: Page = Depends(student_page)):
    return _mock_page(p)


@router.post("/mock-tests", response_class=HTMLResponse)
async def mock_add(request: Request, p: Page = Depends(student_page)):
    f = await request.form()
    try:
        subjects = [mock_api.SubjectIn(subject=s, score=_number(f, s), max_score=m,
                                       weak_topics=[t.strip() for t in (f.get(f"{s}-topics") or "").split(",") if t.strip()])
                    for s, m in MOCK_SUBJECTS if _number(f, s) is not None]
        body = mock_api.MockTestIn(name=_blank(f, "name") or "", provider=_blank(f, "provider"),
                                   test_date=_blank(f, "test_date"), total_score=_number(f, "total_score"),
                                   max_score=_number(f, "max_score") or 720, percentile=_number(f, "percentile"),
                                   notes=_blank(f, "notes"), subjects=subjects)
        mock_api.add_test(body, p.user, p.db)
    except (ValidationError, HTTPException) as e:
        return _mock_page(p, error=error_text(e), status_code=422, open_form=True)
    return _mock_page(p)


@router.delete("/mock-tests/{test_id}", response_class=HTMLResponse)
def mock_delete(test_id: int, p: Page = Depends(student_page)):
    mock_api.delete_test(test_id, p.user, p.db)
    return _mock_page(p)
