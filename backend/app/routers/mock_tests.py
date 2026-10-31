from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import MockTest, MockTestSubjectScore, User
from app.security import current_user
from app.services.mock_analytics import analyse

router = APIRouter(prefix="/api/mock-tests", tags=["mock-tests"])


class SubjectIn(BaseModel):
    subject: str = Field(pattern="^(Physics|Chemistry|Biology)$")
    score: float
    max_score: float = Field(gt=0)
    weak_topics: list[str] = Field(default_factory=list, max_length=30)


class MockTestIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str | None = Field(None, max_length=120)
    test_date: date
    total_score: float
    max_score: float = Field(720, gt=0)
    percentile: float | None = Field(None, ge=0, le=100)
    provider_rank: int | None = Field(None, ge=1)
    notes: str | None = Field(None, max_length=2000)
    subjects: list[SubjectIn] = []

    @model_validator(mode="after")
    def check(self):
        # NEET-style negative marking allows totals below zero, but never above the maximum.
        if self.total_score > self.max_score:
            raise ValueError("Total score cannot exceed the maximum score.")
        if any(s.score > s.max_score for s in self.subjects):
            raise ValueError("A subject score exceeds its maximum.")
        if len({s.subject for s in self.subjects}) != len(self.subjects):
            raise ValueError("Each subject can appear only once.")
        if self.test_date > date.today():
            raise ValueError("Test date cannot be in the future.")
        return self


def _out(t: MockTest) -> dict:
    return {"id": t.id, "name": t.name, "provider": t.provider, "test_date": t.test_date,
            "total_score": t.total_score, "max_score": t.max_score, "percentile": t.percentile,
            "provider_rank": t.provider_rank, "notes": t.notes,
            "subjects": [{"subject": s.subject, "score": s.score, "max_score": s.max_score,
                          "weak_topics": s.weak_topics} for s in t.subjects]}


@router.get("")
def list_tests(user: User = Depends(current_user), db: Session = Depends(get_db)):
    tests = db.scalars(select(MockTest).where(MockTest.user_id == user.id).order_by(MockTest.test_date)).all()
    return [_out(t) for t in tests]


@router.post("", status_code=201)
def add_test(body: MockTestIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = MockTest(user_id=user.id, **body.model_dump(exclude={"subjects"}))
    t.subjects = [MockTestSubjectScore(**s.model_dump()) for s in body.subjects]
    db.add(t)
    db.commit()
    return _out(t)


@router.delete("/{test_id}", status_code=204)
def delete_test(test_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(MockTest, test_id)
    if t is None or t.user_id != user.id:
        raise HTTPException(404, "Not found")
    db.delete(t)
    db.commit()


@router.get("/analytics")
def analytics(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return analyse(list(db.scalars(select(MockTest).where(MockTest.user_id == user.id))))
