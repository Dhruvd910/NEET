"""Sign-in, registration, sign-out, account deletion and guardian consent pages.

They reuse the JSON API's handlers (routers/auth.py), so validation and consent rules are identical.
"""
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.config import get_settings
from app.routers import auth as auth_api
from app.security import record_login
from app.services import google_auth, phone_auth
from app.web.core import Page, page

router = APIRouter(include_in_schema=False)


def _safe_next(url: str | None) -> str:
    return url if url and url.startswith("/") and not url.startswith("//") else "/dashboard"


def _first_error(e: ValidationError) -> str:
    return e.errors()[0]["msg"].removeprefix("Value error, ")


def _countries() -> list[dict]:
    return phone_auth.countries() if get_settings().phone_enabled else []


def hx_redirect(url: str) -> Response:
    """Redirect that works for both HTMX requests and normal form posts."""
    return Response(status_code=204, headers={"HX-Redirect": url})


@router.get("/login", response_class=HTMLResponse)
def login_form(next: str | None = None, p: Page = Depends(page)):
    if p.user:
        return RedirectResponse(_safe_next(next), status_code=303)
    return p.render("auth/login.html", next=next, countries=_countries())


@router.post("/login", response_class=HTMLResponse)
def login(email: str = Form(...), password: str = Form(...), next: str = Form("/dashboard"), p: Page = Depends(page)):
    try:
        body = auth_api.LoginIn(email=email, password=password)
        resp = RedirectResponse(_safe_next(next), status_code=303)
        auth_api.login(body, resp, p.request, p.db)
        return resp
    except ValidationError:
        error = "Enter a valid email address."
    except HTTPException as e:
        error = e.detail
    return p.render("auth/login.html", status_code=400, next=next, email=email, error=error, countries=_countries())


# ---------------------------------------------------------------- admin sign-in (separate from students)

@router.get("/admin/login", response_class=HTMLResponse)
def admin_login_form(p: Page = Depends(page)):
    if p.user is not None and p.user.role.value == "admin":
        return RedirectResponse("/admin", status_code=303)
    return p.render("auth/admin_login.html")


@router.post("/admin/login", response_class=HTMLResponse)
def admin_login(email: str = Form(...), password: str = Form(...), p: Page = Depends(page)):
    """Email + password for admins only. One message for every failure, so it doesn't reveal which accounts exist."""
    from sqlalchemy import select

    from app.models import Role, User
    from app.security import verify_password
    user = p.db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or user.role != Role.admin or not verify_password(password, user.password_hash):
        return p.render("auth/admin_login.html", status_code=401, email=email,
                        error="Incorrect email or password, or this account is not an admin.")
    record_login(p.db, user, "admin", p.request)
    resp = RedirectResponse("/admin", status_code=303)
    auth_api._set_cookie(resp, user)
    return resp


@router.get("/register", response_class=HTMLResponse)
def register_form(p: Page = Depends(page)):
    return p.render("auth/register.html", form={})


@router.post("/register", response_class=HTMLResponse)
def register(email: str = Form(...), password: str = Form(...), minor: str = Form(...), guardian_email: str = Form(""),
             privacy: str | None = Form(None), p: Page = Depends(page)):
    form = {"email": email, "minor": minor, "guardian_email": guardian_email}
    try:
        body = auth_api.RegisterIn(email=email, password=password, is_minor=minor == "yes",
                                   guardian_email=guardian_email or None, accept_privacy_notice=privacy is not None)
        resp = RedirectResponse("/profile", status_code=303)
        auth_api.register(body, resp, p.request, p.db)
        return resp
    except ValidationError as e:
        error = _first_error(e)
    except HTTPException as e:
        error = e.detail
    return p.render("auth/register.html", status_code=400, form=form, error=error)


# ---------------------------------------------------------------- Google sign-in

def _signed_in(p: Page, user, method: str, target: str):
    record_login(p.db, user, method, p.request)
    resp = RedirectResponse(target, status_code=303)
    auth_api._set_cookie(resp, user)
    resp.delete_cookie(google_auth.FLOW_COOKIE, path="/")
    resp.delete_cookie(google_auth.PENDING_COOKIE, path="/")
    return resp


@router.get("/auth/google")
def google_start(next: str | None = None, p: Page = Depends(page)):
    if not get_settings().google_enabled:
        return p.render("auth/login.html", status_code=503, next=next, error="Google sign-in is not set up yet.")
    url, flow = google_auth.start(_safe_next(next))
    resp = RedirectResponse(url, status_code=303)
    # Lax is enough: Google returns with a top-level GET, which carries Lax cookies.
    resp.set_cookie(google_auth.FLOW_COOKIE, flow, max_age=600, httponly=True, samesite="lax",
                    secure=get_settings().cookie_secure, path="/")
    return resp


@router.get("/auth/google/callback", response_class=HTMLResponse)
def google_callback(code: str = "", state: str = "", error: str = "", p: Page = Depends(page)):
    if error or not code:
        return p.render("auth/login.html", status_code=400, error="Google sign-in was cancelled.")
    try:
        claims, target = google_auth.finish(code, state, p.request.cookies.get(google_auth.FLOW_COOKIE))
    except google_auth.GoogleAuthError as e:
        return p.render("auth/login.html", status_code=400, error=str(e))
    user = auth_api.google_user(p.db, claims)
    if user is not None:
        return _signed_in(p, user, "google", target)
    # New here: ask the questions Google can't answer (age, guardian, privacy notice) before creating the account.
    pending = google_auth.sign({"purpose": "google-signup", "sub": claims["sub"], "email": claims["email"],
                                "name": claims.get("name")}, 15)
    resp = RedirectResponse("/register/google", status_code=303)
    resp.set_cookie(google_auth.PENDING_COOKIE, pending, max_age=900, httponly=True, samesite="lax",
                    secure=get_settings().cookie_secure, path="/")
    resp.delete_cookie(google_auth.FLOW_COOKIE, path="/")
    return resp


def _pending(p: Page) -> dict | None:
    return google_auth.unsign(p.request.cookies.get(google_auth.PENDING_COOKIE), "google-signup")


@router.get("/register/google", response_class=HTMLResponse)
def google_signup_form(p: Page = Depends(page)):
    pending = _pending(p)
    if pending is None:
        return RedirectResponse("/login", status_code=303)
    return p.render("auth/register_google.html", g=pending, form={})


@router.post("/register/google", response_class=HTMLResponse)
def google_signup(minor: str = Form(...), guardian_email: str = Form(""), privacy: str | None = Form(None),
                  name: str = Form(""), p: Page = Depends(page)):
    pending = _pending(p)
    if pending is None:
        return p.render("auth/login.html", status_code=400, error="That took too long. Please continue with Google again.")
    name = " ".join(name.split())[:80]
    form = {"minor": minor, "guardian_email": guardian_email, "name": name}
    if len(name) < 2:
        return p.render("auth/register_google.html", status_code=400, g=pending, form=form, error="Please enter your name.")
    try:
        body = auth_api.GoogleSignupIn(is_minor=minor == "yes", guardian_email=guardian_email or None,
                                       accept_privacy_notice=privacy is not None)
        user = auth_api.register_google(p.db, {**pending, "name": name}, body)
    except ValidationError as e:
        return p.render("auth/register_google.html", status_code=400, g=pending, form=form, error=_first_error(e))
    except HTTPException as e:
        return p.render("auth/register_google.html", status_code=400, g=pending, form=form, error=e.detail)
    return _signed_in(p, user, "signup", "/profile")


@router.post("/logout")
def logout():
    resp = hx_redirect("/")
    auth_api._clear_cookies(resp)
    return resp


@router.delete("/account")
def delete_account(p: Page = Depends(page)):
    if p.user is None:
        return hx_redirect("/login")
    p.db.delete(p.user)
    p.db.commit()
    resp = hx_redirect("/")
    auth_api._clear_cookies(resp)
    return resp


@router.post("/guardian-consent-resend", response_class=HTMLResponse)
def resend(p: Page = Depends(page)):
    if p.user is None:
        return HTMLResponse("Please sign in.")
    try:
        r = auth_api.guardian_consent_resend(p.user, p.db)
    except HTTPException as e:
        return HTMLResponse(e.detail)
    return HTMLResponse(f"Sent again to {r['sent_to']}.")


@router.get("/guardian-consent", response_class=HTMLResponse)
def consent_form(token: str = "", p: Page = Depends(page)):
    try:
        info = auth_api.guardian_consent_info(token, p.db) if token else None
    except HTTPException as e:
        return p.render("auth/guardian_consent.html", status_code=404, info=None, error=e.detail)
    return p.render("auth/guardian_consent.html", info=info, token=token)


@router.post("/guardian-consent", response_class=HTMLResponse)
def consent_decide(token: str = Form(...), decision: str = Form(...), guardian_name: str = Form(""),
                   relationship: str = Form(""), confirm: str | None = Form(None), p: Page = Depends(page)):
    try:
        info = auth_api.guardian_consent_info(token, p.db)
        body = auth_api.GuardianDecision(decision=decision, guardian_name=guardian_name, relationship=relationship,
                                         confirm_is_guardian=confirm is not None)
        result = auth_api.guardian_consent_decide(token, body, p.request, p.db)
        return p.render("auth/guardian_consent.html", done=result["status"])
    except ValidationError as e:
        return p.render("auth/guardian_consent.html", status_code=400, info=info, token=token, error=_first_error(e))
    except HTTPException as e:
        return p.render("auth/guardian_consent.html", status_code=404, info=None, error=e.detail)
