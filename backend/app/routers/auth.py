import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import (
    AcademicRecord, ChapterProgress, ChatSession, ConsentRecord, ExamAttempt, ExamProfile, LoginEvent, MockTest,
    PreferenceList, RoadmapItem, SavedCollege, StudentProfile, StudyPlan, User,
)
from app.security import (
    COOKIE_NAME, CSRF_COOKIE, authenticated_user, create_token, csrf_token_for, hash_password, record_login,
    verify_password,
)
from app.services.email import send_email

router = APIRouter(prefix="/api/auth", tags=["auth"])
# Password hash for accounts that sign in by phone or Google: never matches any password.
NO_PASSWORD = "no-password"
# Syntax check only, so reserved test domains (*.test) work for demo accounts.
Email = Annotated[str, Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]


class RegisterIn(BaseModel):
    email: Email
    password: str = Field(min_length=8, max_length=128)
    is_minor: bool
    guardian_email: Email | None = None
    accept_privacy_notice: bool

    @model_validator(mode="after")
    def check_consent(self):
        if not self.accept_privacy_notice:
            raise ValueError("Please read and accept the privacy notice.")
        if self.is_minor:
            if not self.guardian_email:
                raise ValueError("Students under 18 need a parent/guardian's email so they can give consent.")
            if self.guardian_email.lower() == self.email.lower():
                raise ValueError("The parent/guardian's email must be different from yours.")
        return self


class LoginIn(BaseModel):
    email: Email
    password: str


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}{'*' * max(1, len(name) - 2)}@{domain}"


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "role": u.role.value, "is_minor": u.is_minor,
            "has_profile": u.profile is not None, "guardian_consent_status": u.guardian_consent_status,
            "guardian_email": _mask(u.guardian_email) if u.guardian_email else None}


def _set_cookie(resp: Response, user: User):
    s = get_settings()
    token = create_token(user)
    resp.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax",
                    secure=s.cookie_secure, max_age=s.jwt_expiry_minutes * 60, path="/")
    # Readable by the web app, which echoes it in the X-CSRF-Token header on unsafe requests.
    resp.set_cookie(CSRF_COOKIE, csrf_token_for(token), httponly=False, samesite="lax",
                    secure=s.cookie_secure, max_age=s.jwt_expiry_minutes * 60, path="/")


def _clear_cookies(resp: Response):
    resp.delete_cookie(COOKIE_NAME, path="/")
    resp.delete_cookie(CSRF_COOKIE, path="/")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _request_guardian_consent(db: Session, user: User) -> None:
    s = get_settings()
    token = secrets.token_urlsafe(32)
    user.guardian_token_hash = _hash_token(token)
    user.guardian_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=s.guardian_link_hours)
    db.add(ConsentRecord(user_id=user.id, kind="guardian_consent", action="requested",
                         notice_version=s.privacy_notice_version, method="guardian_email_link",
                         details={"guardian_email": _mask(user.guardian_email or "")}))
    link = f"{s.public_app_url.rstrip('/')}/guardian-consent?token={token}"
    send_email(user.guardian_email or "", "Consent needed: your child's NEET Compass account", (
        f"A student account was created on NEET Compass with the email {user.email}, and you were named as "
        "their parent or guardian.\n\n"
        "Because the student is under 18, we will not store any of their personal information (profile, "
        "ranks, mock-test scores, chats) until you review what we collect and give consent:\n\n"
        f"{link}\n\n"
        f"This link expires in {s.guardian_link_hours} hours. If you do not recognise this request, ignore this "
        f"email: the account will be deleted automatically after {s.unconsented_minor_retention_days} days."))


@router.post("/register", status_code=201)
def register(body: RegisterIn, resp: Response, request: Request, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists.")
    user = User(email=email, password_hash=hash_password(body.password), is_minor=body.is_minor,
                guardian_consent=False,
                guardian_consent_status="pending" if body.is_minor else "not_required",
                guardian_email=body.guardian_email.lower() if body.is_minor and body.guardian_email else None)
    db.add(user)
    db.flush()
    db.add(ConsentRecord(user_id=user.id, kind="privacy_notice", action="granted",
                         notice_version=get_settings().privacy_notice_version, method="signup_checkbox"))
    if user.is_minor:
        _request_guardian_consent(db, user)
    db.commit()
    record_login(db, user, "signup", request)
    _set_cookie(resp, user)
    return user_out(user)


@router.post("/login")
def login(body: LoginIn, resp: Response, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is not None and user.password_hash == NO_PASSWORD:
        how = "Google (\"Continue with Google\")" if user.google_sub else "your phone number"
        raise HTTPException(401, f"This account signs in with {how}, not a password.")
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password.")
    record_login(db, user, "password", request)
    _set_cookie(resp, user)
    return user_out(user)


# ---------------------------------------------------------------- Google sign-in (pages in web/routes_auth.py)

class GoogleSignupIn(BaseModel):
    """The questions a Google sign-up still has to answer: Google tells us who, not whether they are under 18."""
    is_minor: bool
    guardian_email: Email | None = None
    accept_privacy_notice: bool

    @model_validator(mode="after")
    def check_consent(self):
        if not self.accept_privacy_notice:
            raise ValueError("Please read and accept the privacy notice.")
        if self.is_minor and not self.guardian_email:
            raise ValueError("Students under 18 need a parent/guardian's email so they can give consent.")
        return self


def google_user(db: Session, claims: dict) -> User | None:
    """The account for a verified Google identity: by Google id, or an existing account with the same (verified)
    email, which is then linked so the student can use either way to sign in."""
    user = db.scalar(select(User).where(User.google_sub == claims["sub"]))
    if user is None:
        user = db.scalar(select(User).where(User.email == claims["email"].lower()))
        if user is not None:
            user.google_sub = claims["sub"]
    if user is not None:
        user.name = user.name or claims.get("name")
        db.commit()
    return user


def register_google(db: Session, claims: dict, body: GoogleSignupIn) -> User:
    email = claims["email"].lower()
    if body.is_minor and body.guardian_email and body.guardian_email.lower() == email:
        raise HTTPException(422, "The parent/guardian's email must be different from yours.")
    if db.scalar(select(User).where((User.email == email) | (User.google_sub == claims["sub"]))):
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    user = User(email=email, password_hash=NO_PASSWORD, google_sub=claims["sub"], name=claims.get("name"),
                is_minor=body.is_minor, guardian_consent=False,
                guardian_consent_status="pending" if body.is_minor else "not_required",
                guardian_email=body.guardian_email.lower() if body.is_minor and body.guardian_email else None)
    db.add(user)
    db.flush()
    db.add(ConsentRecord(user_id=user.id, kind="privacy_notice", action="granted",
                         notice_version=get_settings().privacy_notice_version, method="signup_checkbox_google"))
    if user.is_minor:
        _request_guardian_consent(db, user)
    db.commit()
    return user


@router.post("/logout")
def logout(resp: Response):
    _clear_cookies(resp)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(authenticated_user)):
    return user_out(user)


# ---------------------------------------------------------------- guardian consent (minors)

def _user_for_token(db: Session, token: str) -> User:
    user = db.scalar(select(User).where(User.guardian_token_hash == _hash_token(token)))
    expires = user.guardian_token_expires_at if user else None
    if expires is not None and expires.tzinfo is None:  # SQLite returns naive datetimes
        expires = expires.replace(tzinfo=timezone.utc)
    if user is None or expires is None or expires < datetime.now(timezone.utc):
        raise HTTPException(404, "This consent link is invalid or has expired. The student can send a new one.")
    return user


@router.get("/guardian-consent/{token}")
def guardian_consent_info(token: str, db: Session = Depends(get_db)):
    user = _user_for_token(db, token)
    return {"student_email": _mask(user.email), "status": user.guardian_consent_status,
            "notice_version": get_settings().privacy_notice_version}


class GuardianDecision(BaseModel):
    decision: Literal["approve", "decline"]
    guardian_name: str = Field(min_length=2, max_length=120)
    relationship: str = Field(min_length=2, max_length=40)
    confirm_is_guardian: bool

    @model_validator(mode="after")
    def check(self):
        if not self.confirm_is_guardian:
            raise ValueError("Please confirm that you are the student's parent or legal guardian.")
        return self


@router.post("/guardian-consent/{token}")
def guardian_consent_decide(token: str, body: GuardianDecision, request: Request, db: Session = Depends(get_db)):
    user = _user_for_token(db, token)
    approved = body.decision == "approve"
    user.guardian_consent_status = "verified" if approved else "declined"
    user.guardian_consent = approved
    user.guardian_consent_at = datetime.now(timezone.utc)
    user.guardian_token_hash = user.guardian_token_expires_at = None  # single use
    db.add(ConsentRecord(user_id=user.id, kind="guardian_consent", action="granted" if approved else "declined",
                         notice_version=get_settings().privacy_notice_version, method="guardian_email_link",
                         details={"guardian_name": body.guardian_name, "relationship": body.relationship,
                                  "ip": request.client.host if request.client else None}))
    db.commit()
    return {"status": user.guardian_consent_status}


@router.post("/guardian-consent-resend")
def guardian_consent_resend(user: User = Depends(authenticated_user), db: Session = Depends(get_db)):
    if user.guardian_consent_status != "pending":
        raise HTTPException(409, "Guardian consent is not pending for this account.")
    _request_guardian_consent(db, user)
    db.commit()
    return {"ok": True, "sent_to": _mask(user.guardian_email or "")}


# ---------------------------------------------------------------- data rights

@router.get("/me/export")
def export_my_data(user: User = Depends(authenticated_user), db: Session = Depends(get_db)):
    """Everything we store about the student, as JSON (data-portability)."""
    def rows(model):
        return [{c.name: getattr(r, c.name) for c in model.__table__.columns}
                for r in db.scalars(select(model).where(model.user_id == user.id))]
    data = {"account": {"email": user.email, "phone": user.phone, "name": user.name, "created_at": user.created_at,
                        "is_minor": user.is_minor, "guardian_consent_status": user.guardian_consent_status,
                        "guardian_email": user.guardian_email, "signs_in_with_google": bool(user.google_sub),
                        "last_login_at": user.last_login_at, "login_count": user.login_count}}
    for model in (LoginEvent, StudentProfile, ExamProfile, AcademicRecord, MockTest, SavedCollege, PreferenceList,
                  RoadmapItem, ChatSession, ConsentRecord, ExamAttempt, ChapterProgress, StudyPlan):
        data[model.__tablename__] = rows(model)
    return data


@router.delete("/me", status_code=204)
def delete_account(resp: Response, user: User = Depends(authenticated_user), db: Session = Depends(get_db)):
    """Permanently deletes the account and all personal data (cascades)."""
    db.delete(user)
    db.commit()
    _clear_cookies(resp)
