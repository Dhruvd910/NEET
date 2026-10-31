"""Compare colleges and the counselling centre (authorities, guides and the draft preference list)."""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from app.routers import counselling as counselling_api
from app.routers.colleges import PredictIn
from app.security import has_consent
from app.services.compare import PRIORITIES, CompareError, compare
from app.web.core import Page, page
from app.web.routes_student import error_text

router = APIRouter(include_in_schema=False)

COMPARE_DEFAULT = ["cost", "cutoff", "hostel"]


@router.get("/compare", response_class=HTMLResponse)
def compare_page(p: Page = Depends(page), ids: str = "", prio: list[str] = Query(default=[]), set_: str = Query("", alias="set")):
    college_ids = list(dict.fromkeys(int(x) for x in ids.split(",") if x.strip().isdigit()))[:5]
    chosen = [x for x in prio if x in PRIORITIES] if set_ else COMPARE_DEFAULT
    res, error = None, None
    if len(college_ids) >= 2:
        try:
            res = compare(p.db, college_ids, chosen)
        except CompareError as e:
            error = str(e)
    return p.render("compare.html", ids=college_ids, chosen=chosen, PRIORITIES=PRIORITIES, res=res, error=error)


# ------------------------------------------------------------------ counselling

PRIORITY_LABELS = {"government_first": "Government / central colleges first", "preferred_states": "My preferred states first",
                   "lower_cost": "Lower cost first", "fit": "Stronger historical fit first"}
DRAFT_QUOTAS = {"AIQ", "STATE", "DEEMED", "CENTRAL", "MANAGEMENT"}


def _move(xs: list, i: int, d: int) -> list:
    xs = list(xs)
    if 0 <= i < len(xs):
        x = xs.pop(i)
        xs.insert(max(0, min(len(xs), i + d)), x)
    return xs


def _counselling(p: Page, form: dict | None = None, draft: dict | None = None, msg=None, error=None, status_code=200):
    can_save = p.user is not None and has_consent(p.user)
    return p.render("counselling.html", status_code=status_code, authorities=counselling_api.authorities(p.db),
                    articles=counselling_api.info("counselling", p.db), PRIORITY_LABELS=PRIORITY_LABELS,
                    f=form or {"authority": "MCC", "air": "", "state_rank": "", "category": "", "domicile": "",
                               "year": date.today().year, "priorities": list(PRIORITY_LABELS)},
                    draft=draft, msg=msg, error=error, can_save=can_save,
                    lists=counselling_api.list_prefs(p.user, p.db) if can_save else [])


@router.get("/counselling", response_class=HTMLResponse)
def counselling(p: Page = Depends(page)):
    return _counselling(p)


@router.post("/counselling/draft", response_class=HTMLResponse)
async def counselling_draft(request: Request, p: Page = Depends(page)):
    """One form drives the whole draft builder; the clicked button's `op` says what to do."""
    raw = await request.form()
    priorities = [x for x in raw.getlist("priorities") if x in PRIORITY_LABELS] or list(PRIORITY_LABELS)
    f = {k: (raw.get(k) or "").strip() for k in ("authority", "air", "state_rank", "category", "domicile", "year")}
    f["priorities"] = priorities
    try:
        draft = json.loads(raw.get("draft_json") or "null")
    except ValueError:
        draft = None
    op = raw.get("op") or "build"
    kind, _, rest = op.partition(":")
    msg = error = None
    try:
        if kind == "prio":
            i, d = map(int, rest.split(":"))
            f["priorities"] = _move(priorities, i, d)
        elif kind == "item" and draft:
            i, d = rest.split(":")
            draft["items"] = [x for j, x in enumerate(draft["items"]) if j != int(i)] if d == "x" else _move(draft["items"], int(i), int(d))
        elif kind == "save" and draft:
            if p.user is None or not has_consent(p.user):
                raise HTTPException(401, "Sign in to save your draft.")
            counselling_api.create_pref(counselling_api.PrefListIn(
                name=f"{f['authority']} draft {date.today().strftime('%d/%m/%Y')}", authority_code=f["authority"],
                exam_year=int(f["year"] or date.today().year), course_code="MBBS",
                items=[counselling_api.PrefItem(**{k: x.get(k) for k in ("college_id", "college_name", "quota", "authority",
                                                                          "historical_fit", "note")}) for x in draft["items"]]),
                p.user, p.db)
            msg = "Draft saved. Remember: it is not submitted anywhere."
        else:
            auth = next((a for a in counselling_api.authorities(p.db) if a["code"] == f["authority"]), None)
            quotas = [q for q in (auth["quotas"] if auth else ["AIQ"]) if q in DRAFT_QUOTAS]
            num = lambda k: int(f[k]) if f[k].isdigit() else None  # noqa: E731
            draft = counselling_api.draft_pref(counselling_api.DraftIn(
                authority_code=f["authority"], priorities=f["priorities"],
                predict=PredictIn(exam_year=num("year") or date.today().year, air=num("air"), state_rank=num("state_rank"),
                                  category=f["category"] or None, domicile_state=f["domicile"] or None, quotas=quotas)), p.db)
    except (HTTPException, ValidationError, ValueError) as e:
        error = error_text(e)
    return _counselling(p, f, draft, msg, error, 422 if error else 200)


@router.post("/counselling/lists/{pid}/delete", response_class=HTMLResponse)
def delete_list(pid: int, p: Page = Depends(page)):
    if p.user is not None and has_consent(p.user):
        counselling_api.delete_pref(pid, p.user, p.db)
    return _counselling(p)
