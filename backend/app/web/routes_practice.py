"""Practice tests: the exam hall, exam-day steps, the exam room and the scorecard.

The exam room is server-rendered. Each click (choose an option, mark, clear, move) is one HTMX request that
saves the answer and returns the room again. A small script (static/js/exam-room.js) only runs the clock,
the bells, full screen, the rough-work pad, and adds the seconds spent on the current question to each request.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from markupsafe import Markup, escape
from pydantic import ValidationError

from app.routers import practice as practice_api
from app.services import exams
from app.web.core import Page, student_page, templates
from app.web.routes_auth import hx_redirect
from app.web.routes_student import error_text

router = APIRouter(include_in_schema=False)

MODES = {
    "full": ("Full NEET mock", "180 questions · 3 hours · exam-day flow with admit card and OMR sheet.", "Clipboard"),
    "mini": ("Mini NEET mock", "Same format and 1 minute per question, fewer questions per section.", "Clock"),
    "subject": ("Subject practice", "One subject, timed at 1 minute per question.", "Sparkle"),
    "chapter": ("Chapter / topic test", "Pick up to 10 chapters.", "Target"),
    "weak": ("My weak chapters", "Chapters where you scored under 60% before.", "HeartPulse"),
}
ANNOUNCEMENTS = {1800: "Invigilator: 30 minutes remaining.",
                 600: "Invigilator: 10 minutes remaining. Check your OMR sheet.",
                 300: "Invigilator: 5 minutes remaining. Make sure every answer is darkened on the OMR sheet."}
REPORT_REASONS = [("wrong_answer", "The answer key is wrong"), ("unclear", "Unclear or two options correct"),
                  ("out_of_syllabus", "Not in the NEET syllabus"), ("typo", "Typo or formatting"), ("other", "Something else")]

_LIST_ROW = re.compile(r"^\s*[A-D][.)]\s.+\|\s*[IVX]+[.)]\s")
_STATEMENT = re.compile(r"^\s*([A-D]|Assertion \(A\)|Reason \(R\))[.:)]")


def stem_html(text: str) -> Markup:
    """Question text as printed in the booklet: statements on their own lines, and "A. item | I. item" rows
    from match-the-list questions laid out as a List-I / List-II table."""
    lines = text.split("\n")
    rows = [l for l in lines if _LIST_ROW.match(l)]
    out, table_done = [], False
    cell = 'class="border border-slate-300 px-2 py-1 align-top"'
    for line in lines:
        if line in rows:
            if not table_done:
                table_done = True
                body = "".join(f"<tr><td {cell}>{escape(a.strip())}</td><td {cell}>{escape(b.strip())}</td></tr>"
                               for a, b in (r.split("|", 1) for r in rows))
                out.append('<table class="my-2 w-full border-collapse text-[0.95em]"><thead><tr>'
                           '<th class="w-1/2 border border-slate-300 px-2 py-1 text-left">List-I</th>'
                           f'<th class="border border-slate-300 px-2 py-1 text-left">List-II</th></tr></thead><tbody>{body}</tbody></table>')
            continue
        if line.strip():
            out.append(f'<p{" class=\"pl-4\"" if _STATEMENT.match(line) else ""}>{escape(line)}</p>')
    return Markup('<div class="space-y-1.5">' + "".join(out) + "</div>")


templates.env.filters["stem"] = stem_html


def _attempt(p: Page, attempt_id: int):
    return practice_api._own_attempt(p.db, p.user, attempt_id)


def _num(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ exam hall

def _readiness(p: Page) -> dict:
    return exams.readiness(p.db, p.user)


@router.get("/practice", response_class=HTMLResponse)
def hall(p: Page = Depends(student_page), mode: str | None = None, chapter: int | None = None):
    attempts = practice_api.list_attempts(p.user, p.db)
    chapters = practice_api.syllabus(p.db)["chapters"]
    pre = next((c for c in chapters if c["id"] == chapter), None)
    mode = "chapter" if pre else (mode if mode in MODES else None)
    return p.render("practice/hall.html", MODES=MODES, mode=mode, attempts=attempts, chapters=chapters,
                    pre_chapter=pre, pattern=exams.NEET_PATTERN, r=_readiness(p),
                    perf=practice_api.performance(p.user, p.db),
                    in_progress=next((a for a in attempts if a["status"] == "in_progress"), None))


@router.get("/practice/readiness", response_class=HTMLResponse)
def readiness_panel(p: Page = Depends(student_page)):
    return p.render("practice/_readiness.html", r=_readiness(p))


@router.post("/practice/prepare", response_class=HTMLResponse)
async def prepare(request: Request, p: Page = Depends(student_page)):
    f = await request.form()
    mode = f.get("mode")
    body = {"mode": mode, "strict_omr": bool(f.get("strict_omr"))}
    if mode == "mini":
        body["count"] = _num(f.get("per_section"), 10)
    elif mode == "subject":
        body.update(subject=f.get("subject"), count=_num(f.get("count"), 20))
    elif mode == "chapter":
        body.update(chapter_ids=[int(x) for x in f.getlist("chapter_ids") if x.isdigit()], count=_num(f.get("count"), 20))
    elif mode == "weak":
        body["count"] = _num(f.get("count"), 20)
    try:
        if mode == "chapter" and not body["chapter_ids"]:
            raise HTTPException(422, "Pick at least one chapter.")
        a = exams.create_attempt(p.db, p.user, mode, subject=body.get("subject"), chapter_ids=body.get("chapter_ids"),
                                 count=practice_api.AttemptIn(**body).count, strict_omr=body["strict_omr"])
    except exams.PaperNotReady as e:
        p.db.rollback()
        if e.generating:  # fresh questions are being written; this panel posts the same form again shortly
            return p.render("practice/_preparing.html", detail=str(e), values=list(f.multi_items()))
        return p.render("practice/_prepare_error.html", error=str(e), status_code=422)
    except (exams.ExamError, ValidationError, HTTPException) as e:
        return p.render("practice/_prepare_error.html", error=error_text(e), status_code=422)
    return hx_redirect(f"/practice/{a.id}")


# ------------------------------------------------------------------ one test: exam day, room, scorecard

def _room(p: Page, view: dict, cur: int, message: str | None = None, partial: bool = False):
    qs = view["questions"]
    cur = max(0, min(cur, len(qs) - 1))
    sections = []
    for s in view["section_counts"]:
        idx = [i for i, q in enumerate(qs) if q["section"] == s]
        sections.append({"name": s, "first": idx[0], "done": sum(qs[i]["selected_index"] is not None for i in idx),
                         "total": len(idx)})
    answered = sum(q["selected_index"] is not None for q in qs)
    ctx = dict(v=view, qs=qs, cur=cur, q=qs[cur], sections=sections, answered=answered,
               marked=sum(q["marked_for_review"] for q in qs), message=message, ANNOUNCEMENTS=ANNOUNCEMENTS,
               first_of_section=cur == 0 or qs[cur - 1]["section"] != qs[cur]["section"])
    return p.render("practice/_room.html" if partial else "practice/room.html", **ctx)


@router.get("/practice/{attempt_id}", response_class=HTMLResponse)
def attempt_page(attempt_id: int, p: Page = Depends(student_page), step: int = 1, filter: str = "wrong"):  # noqa: A002
    a = _attempt(p, attempt_id)
    view = exams.attempt_view(p.db, a)
    if view["status"] == "ready":
        prof = p.user.profile
        name = (prof.display_name if prof else None) or p.user.email
        return p.render("practice/exam_day.html", v=view, step=step if step in (1, 2, 3) else 1, name=name,
                        total=sum(view["section_counts"].values()), minutes=round(view["duration_seconds"] / 60),
                        code=view["booklet_code"] or "Q1", error=None, roll="", series="", num="")
    if view["status"] == "submitted":
        qs = view["questions"]
        flt = filter if filter in ("wrong", "skipped", "marked", "correct", "all") else "wrong"
        shown = [q for q in qs if flt == "all" or (q["marked_for_review"] if flt == "marked" else q["outcome"] == flt)]
        r = view["result"]
        return p.render("practice/result.html", v=view, r=r, shown=shown, flt=flt, REASONS=REPORT_REASONS,
                        pct=max(0, round(100 * r["score"] / r["max_score"])) if r["max_score"] else 0)
    qs = view["questions"]
    first_unvisited = next((i for i, q in enumerate(qs) if not q["visited"]), 0)
    return _room(p, view, first_unvisited)


@router.post("/practice/{attempt_id}/start", response_class=HTMLResponse)
async def start(attempt_id: int, request: Request, p: Page = Depends(student_page)):
    """Opens the sealed booklet once the OMR particulars match the admit card, like the real sheet."""
    a = _attempt(p, attempt_id)
    f = await request.form()
    roll, series, num = (f.get("roll") or "").strip(), f.get("series") or "", f.get("num") or ""
    code = a.booklet_code or "Q1"
    error = None
    if roll != a.roll_number:
        error = "That roll number doesn't match your admit card."
    elif series + num != code:
        error = f"The booklet code you darkened doesn't match the booklet ({code})."
    if error:
        view = exams.attempt_view(p.db, a)
        return p.render("practice/exam_day.html", status_code=422, v=view, step=3, name="", code=code, error=error,
                        total=sum(view["section_counts"].values()), minutes=round(view["duration_seconds"] / 60),
                        roll=roll, series=series, num=num)
    if a.status == "ready":
        exams.start_attempt(p.db, a)
    if not p.is_htmx:
        return RedirectResponse(f"/practice/{attempt_id}", status_code=303)
    # Swap the exam room into the current page instead of loading a new one, so full screen stays on.
    resp = _room(p, exams.attempt_view(p.db, a), 0)
    resp.headers.update({"HX-Retarget": "#exam-day", "HX-Reselect": "#exam-room", "HX-Reswap": "outerHTML",
                         "HX-Push-Url": f"/practice/{attempt_id}", "HX-Trigger": "exam-started"})
    return resp


@router.post("/practice/{attempt_id}/act", response_class=HTMLResponse)
async def act(attempt_id: int, request: Request, p: Page = Depends(student_page)):
    """One click in the exam room. Records time on the question being left, applies the action, re-renders."""
    a = _attempt(p, attempt_id)
    f = await request.form()
    items = {i.position: i for i in a.items}
    positions = sorted(items)
    cur, target = _num(f.get("cur"), 0), _num(f.get("target"), _num(f.get("cur"), 0))
    op, elapsed = f.get("op") or "go", max(0, _num(f.get("elapsed"), 0))
    message = None
    try:
        if a.status != "in_progress" or exams.expire_if_due(p.db, a):
            return hx_redirect(f"/practice/{attempt_id}")
        if 0 <= cur < len(positions) and elapsed:
            it = items[positions[cur]]
            exams.save_answer(p.db, a, it.position, selected_index=it.selected_index,
                              marked_for_review=it.marked_for_review, time_spent_delta=elapsed)
        target = max(0, min(target, len(positions) - 1))
        it = items[positions[target]]
        if op == "choose":
            exams.save_answer(p.db, a, it.position, selected_index=_num(f.get("option")),
                              marked_for_review=it.marked_for_review, time_spent_delta=0)
        elif op == "mark":
            exams.save_answer(p.db, a, it.position, selected_index=it.selected_index,
                              marked_for_review=not it.marked_for_review, time_spent_delta=0)
        elif op == "clear" and not a.strict_omr:
            exams.save_answer(p.db, a, it.position, selected_index=None,
                              marked_for_review=it.marked_for_review, time_spent_delta=0)
        else:
            exams.save_answer(p.db, a, it.position, selected_index=it.selected_index,
                              marked_for_review=it.marked_for_review, time_spent_delta=0)
    except exams.ExamError as e:
        if str(e).startswith("Time is up"):
            return hx_redirect(f"/practice/{attempt_id}")
        message = str(e)
    return _room(p, exams.attempt_view(p.db, a), target, message, partial=True)


@router.post("/practice/{attempt_id}/submit", response_class=HTMLResponse)
async def submit(attempt_id: int, request: Request, p: Page = Depends(student_page)):
    a = _attempt(p, attempt_id)
    f = await request.form()
    try:
        exams.submit(p.db, a, auto=bool(f.get("auto")))
    except exams.ExamError:
        pass  # already submitted or never started; the page shows the right state
    exams.readiness(p.db, p.user)  # refill this student's unseen pool in the background
    return hx_redirect(f"/practice/{attempt_id}")


@router.post("/practice/{attempt_id}/report/{position}", response_class=HTMLResponse)
async def report(attempt_id: int, position: int, request: Request, p: Page = Depends(student_page)):
    f = await request.form()
    try:
        body = practice_api.ReportIn(reason=f.get("reason") or "other", note=(f.get("note") or "").strip() or None)
        exams.report_question(p.db, _attempt(p, attempt_id), position, p.user, body.reason, body.note)
    except (exams.ExamError, ValidationError) as e:
        return HTMLResponse(f'<p class="text-xs text-red-700">{escape(error_text(e))}</p>', status_code=422)
    return HTMLResponse('<p class="text-xs text-emerald-700">Thanks — reported. Questions with several reports are '
                        'hidden until checked.</p>')
