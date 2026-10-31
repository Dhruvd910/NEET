"""The NEET assistant: saved chats in a sidebar, answers with sources, and (in assistant.js) voice in and out."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from markupsafe import Markup, escape
from pydantic import ValidationError

from app.routers import assistant as assistant_api
from app.web.core import Page, student_page, templates
from app.web.routes_student import error_text

router = APIRouter(include_in_schema=False)

IST = ZoneInfo("Asia/Kolkata")
SUGGESTIONS = [("Which colleges might be realistic for my rank?", "Predictor"),
               ("How does AIQ differ from state quota?", "Counselling"),
               ("What documents should I prepare for counselling?", "Counselling"),
               ("What should I improve based on my mock tests?", "Mock tests"),
               ("What are alternatives to MBBS?", "Careers")]
GROUPS = ["Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"]


def _local(v) -> datetime | None:
    """The database stores naive UTC timestamps; show them in Indian time."""
    if v is None:
        return None
    if isinstance(v, str):
        v = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(IST)


def _group(v) -> str:
    d = _local(v)
    if d is None:
        return "Older"
    days = (datetime.now(IST).date() - d.date()).days
    return "Today" if days <= 0 else "Yesterday" if days == 1 else "Previous 7 days" if days < 7 \
        else "Previous 30 days" if days < 30 else "Older"


_INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*\n]+\*)")


def chat_text(s: str) -> Markup:
    """Small, safe markdown: **bold**, *italic*, bullet lines and line breaks. Everything else is escaped."""
    def inline(t: str) -> str:
        out = []
        for part in _INLINE.split(t):
            if part.startswith("**") and part.endswith("**") and len(part) > 4:
                out.append(f"<strong>{escape(part[2:-2])}</strong>")
            elif part.startswith("*") and part.endswith("*") and len(part) > 2:
                out.append(f"<em>{escape(part[1:-1])}</em>")
            else:
                out.append(str(escape(part)))
        return "".join(out)

    html = []
    for line in s.split("\n"):
        if not line.strip():
            html.append('<span class="block h-2"></span>')
        elif re.match(r"^\s*[-•]\s+", line):
            html.append('<p class="flex gap-2 pl-1"><span class="mt-[0.45em] h-1.5 w-1.5 shrink-0 rounded-full bg-teal-500"></span>'
                        f"<span>{inline(re.sub(r'^\s*[-•]\s+', '', line))}</span></p>")
        else:
            html.append(f"<p>{inline(line)}</p>")
    return Markup("".join(html))


templates.env.filters.update(chat_text=chat_text, ist_clock=lambda v: _local(v).strftime("%H:%M") if v else "",
                             ist_short=lambda v: f"{_local(v).day} {_local(v):%b}" if v else "",
                             ist_long=lambda v: f"{_local(v):%a}, {_local(v).day} {_local(v):%b %Y} · {_local(v):%H:%M}" if v else "")


def _render(p: Page, chat_id: int | None, q: str = "", error: str | None = None, speak: bool = False, status_code=200):
    chats = assistant_api.sessions(p.user, p.db)
    current, messages = None, []
    if chat_id:
        try:
            current = assistant_api.get_session(chat_id, p.user, p.db)
            messages = current["messages"]
        except HTTPException:
            current = None
    needle = q.strip().lower()
    shown = [c for c in chats if not needle or needle in (c["title"] or "").lower()]
    groups = [(g, [c for c in shown if _group(c["updated_at"]) == g]) for g in GROUPS]
    resp = p.render("assistant.html", status_code=status_code, chats=chats, groups=[x for x in groups if x[1]], q=q,
                    current=current, messages=messages, error=error, speak=speak, SUGGESTIONS=SUGGESTIONS)
    if current:
        resp.headers["HX-Push-Url"] = f"/assistant?chat={current['id']}"
    return resp


@router.get("/assistant", response_class=HTMLResponse)
def assistant(p: Page = Depends(student_page), chat: int | None = None, q: str = ""):
    return _render(p, chat, q)


@router.post("/assistant/send", response_class=HTMLResponse)
async def send(request: Request, p: Page = Depends(student_page)):
    f = await request.form()
    sid = int(f["session_id"]) if (f.get("session_id") or "").isdigit() else None
    voice = f.get("voice") == "1"
    try:
        body = assistant_api.MessageIn(session_id=sid, content=(f.get("content") or "").strip(), voice=voice)
        sid = assistant_api.post_message(body, p.user, p.db)["session_id"]
    except (ValidationError, HTTPException) as e:
        p.db.rollback()
        return _render(p, sid, error=error_text(e), status_code=422)
    return _render(p, sid, speak=voice)


@router.post("/assistant/{chat_id}/delete", response_class=HTMLResponse)
async def delete(chat_id: int, request: Request, p: Page = Depends(student_page)):
    f = await request.form()
    try:
        assistant_api.delete_session(chat_id, p.user, p.db)
    except HTTPException:
        pass
    current = int(f["current"]) if (f.get("current") or "").isdigit() else None
    resp = _render(p, None if current == chat_id else current)
    if current == chat_id:
        resp.headers["HX-Push-Url"] = "/assistant"
    return resp
