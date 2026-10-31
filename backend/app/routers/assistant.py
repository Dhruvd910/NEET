from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ChatMessage, ChatSession, User
from app.security import current_user
from app.services.assistant import answer

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

HISTORY_TURNS = 12


class MessageIn(BaseModel):
    session_id: int | None = None
    content: str = Field(min_length=1, max_length=4000)
    voice: bool = False  # spoken conversation: short, plain-speech replies


def _msg(m: ChatMessage) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "citations": m.citations,
            "tool_calls": [c["tool"] for c in m.tool_calls], "created_at": m.created_at}


@router.get("/sessions")
def sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ChatSession).where(ChatSession.user_id == user.id)
                      .order_by(ChatSession.id.desc()).limit(100)).all()
    return [{"id": s.id, "title": s.title, "created_at": s.created_at,
             # last activity drives the "Today / Yesterday" grouping in the history sidebar
             "updated_at": s.messages[-1].created_at if s.messages else s.created_at,
             "message_count": len(s.messages)} for s in rows]


@router.get("/sessions/{sid}")
def get_session(sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(ChatSession, sid)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "Not found")
    return {"id": s.id, "title": s.title, "created_at": s.created_at,
            "messages": [_msg(m) for m in s.messages]}


@router.delete("/sessions/{sid}", status_code=204)
def delete_session(sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(ChatSession, sid)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "Not found")
    db.delete(s)
    db.commit()


@router.post("/messages")
def post_message(body: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.session_id:
        s = db.get(ChatSession, body.session_id)
        if s is None or s.user_id != user.id:
            raise HTTPException(404, "Session not found")
    else:
        s = ChatSession(user_id=user.id, title=body.content[:80])
        db.add(s)
        db.flush()
    db.add(ChatMessage(session_id=s.id, role="user", content=body.content))
    db.flush()
    db.refresh(s)
    history = [{"role": m.role, "content": m.content} for m in s.messages[-HISTORY_TURNS:]]
    reply = answer(db, user, history, voice=body.voice)
    msg = ChatMessage(session_id=s.id, role="assistant", content=reply.content,
                      tool_calls=reply.tool_calls, citations=reply.citations)
    db.add(msg)
    db.commit()
    return {"session_id": s.id, "backend": reply.backend, "message": _msg(msg)}
