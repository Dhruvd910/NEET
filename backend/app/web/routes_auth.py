"""Sign-in, registration, sign-out, account deletion and guardian consent pages.

They reuse the JSON API's handlers (routers/auth.py), so validation and consent rules are identical.
"""
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.routers import auth as auth_api
from app.web.core import Page, page

router = APIRouter(include_in_schema=False)


def _safe_next(url: str | None) -> str:
    return url if url and url.startswith("/") and not url.startswith("//") else "/dashboard"


def _first_error(e: ValidationError) -> str:
    return e.errors()[0]["msg"].removeprefix("Value error, ")


def hx_redirect(url: str) -> Response:
    """Redirect that works for both HTMX requests and normal form posts."""
    return Response(status_code=204, headers={"HX-Redirect": url})


@router.get("/login", response_class=HTMLResponse)
def login_form(next: str | None = None, p: Page = Depends(page)):
    if p.user:
        return RedirectResponse(_safe_next(next), status_code=303)
    return p.render("auth/login.html", next=next)


@router.post("/login", response_class=HTMLResponse)
def login(email: str = Form(...), password: str = Form(...), next: str = Form("/dashboard"), p: Page = Depends(page)):
    try:
        body = auth_api.LoginIn(email=email, password=password)
        resp = RedirectResponse(_safe_next(next), status_code=303)
        auth_api.login(body, resp, p.db)
        return resp
    except ValidationError:
        error = "Enter a valid email address."
    except HTTPException as e:
        error = e.detail
    return p.render("auth/login.html", status_code=400, next=next, email=email, error=error)


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
        auth_api.register(body, resp, p.db)
        return resp
    except ValidationError as e:
        error = _first_error(e)
    except HTTPException as e:
        error = e.detail
    return p.render("auth/register.html", status_code=400, form=form, error=error)


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
