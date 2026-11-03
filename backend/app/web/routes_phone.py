"""Phone sign-in pages: number -> (new users: name, 18+ and terms) -> SMS code -> signed in.

The steps between pages are carried in a short-lived signed cookie (phone, reqId, cooldown), so nothing about a
half-finished sign-in is stored in the database. Under-18s are sent to the email sign-up, which asks a parent.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.config import get_settings
from app.models import ConsentRecord, User
from app.routers import auth as auth_api
from app.security import record_login
from app.services import google_auth, phone_auth
from app.web.core import Page, page
from app.web.routes_auth import _safe_next

router = APIRouter(include_in_schema=False)
FLOW_COOKIE = "neet_phone_flow"


def _flow(p: Page) -> dict | None:
    return google_auth.unsign(p.request.cookies.get(FLOW_COOKIE), "phone-flow")


def _with_flow(resp, flow: dict):
    resp.set_cookie(FLOW_COOKIE, google_auth.sign({**flow, "purpose": "phone-flow"}, 10), max_age=600, httponly=True,
                    samesite="lax", secure=get_settings().cookie_secure, path="/")
    return resp


def _code_page(p: Page, flow: dict, error: str | None = None, status_code: int = 200):
    wait = max(0, int(flow.get("sent_at", 0) + get_settings().otp_resend_seconds - time.time()))
    return p.render("auth/phone_code.html", status_code=status_code, phone=flow["phone"], error=error, wait=wait,
                    test_mode=flow.get("stub", False))


def _send(p: Page, flow: dict):
    """Texts a code and shows the code page; errors (bad number, too many requests) go back to the number page."""
    try:
        flow["req"] = phone_auth.send_code(flow["phone"], {"displayName": flow["name"]} if flow.get("name") else None)
    except phone_auth.PhoneAuthError as e:
        return p.render("auth/login.html", status_code=400, next=flow.get("next"), phone_error=str(e),
                        countries=phone_auth.countries(), number=flow["phone"])
    flow["sent_at"] = int(time.time())
    flow["stub"] = flow["req"].startswith("stub-")  # the service's test mode: no SMS, fixed code
    return _with_flow(_code_page(p, flow), flow)


@router.post("/login/phone", response_class=HTMLResponse)
def phone_start(dial: str = Form("+91"), number: str = Form(...), next: str = Form("/dashboard"), p: Page = Depends(page)):
    phone = phone_auth.normalize(dial, number)
    if not phone_auth.valid(phone):
        return p.render("auth/login.html", status_code=400, next=next, countries=phone_auth.countries(), number=number,
                        phone_error="Enter your mobile number with its country code, e.g. 98765 43210 for India.")
    flow = {"phone": phone, "next": _safe_next(next)}
    if p.db.scalar(select(User).where(User.phone == phone)) is None:
        # New to NEET Compass: ask for a name and the 18+ / terms confirmations before texting a code.
        return _with_flow(p.render("auth/phone_signup.html", phone=phone, form={}), flow)
    return _send(p, flow)


@router.post("/login/phone/signup", response_class=HTMLResponse)
def phone_signup(name: str = Form(""), adult: str | None = Form(None), terms: str | None = Form(None),
                 p: Page = Depends(page)):
    flow = _flow(p)
    if flow is None:
        return RedirectResponse("/login", status_code=303)
    name = " ".join(name.split())[:80]
    error = ("Please enter your name." if len(name) < 2 else
             "Phone sign-up is for students aged 18 or over. Under 18? Use email sign-up so a parent can give consent."
             if adult is None else "Please accept the terms and privacy notice." if terms is None else None)
    if error:
        return p.render("auth/phone_signup.html", status_code=400, phone=flow["phone"], error=error,
                        form={"name": name, "adult": adult, "terms": terms})
    return _send(p, {**flow, "name": name, "consented": True})


@router.post("/login/phone/resend", response_class=HTMLResponse)
def phone_resend(p: Page = Depends(page)):
    flow = _flow(p)
    if flow is None:
        return RedirectResponse("/login", status_code=303)
    if time.time() < flow.get("sent_at", 0) + get_settings().otp_resend_seconds:
        return _code_page(p, flow, error="Please wait a little before asking for another code.", status_code=429)
    return _send(p, flow)


@router.post("/login/phone/verify", response_class=HTMLResponse)
def phone_verify(otp: str = Form(...), p: Page = Depends(page)):
    flow = _flow(p)
    if flow is None or not flow.get("req"):
        return p.render("auth/login.html", status_code=400, countries=phone_auth.countries(),
                        phone_error="That took too long. Please enter your number again.")
    code = "".join(ch for ch in otp if ch.isdigit())
    try:
        who = phone_auth.verify_code(flow["req"], code)
    except phone_auth.PhoneAuthError as e:
        if e.code == "SIGNUP_REQUIRED":  # the service doesn't know this number yet: collect the sign-up details
            return _with_flow(p.render("auth/phone_signup.html", phone=flow["phone"], form={}), flow)
        if e.code == "PENDING_APPROVAL":
            return p.render("auth/login.html", status_code=403, countries=phone_auth.countries(),
                            phone_error="This number is waiting for a parent's approval.")
        return _code_page(p, flow, error=str(e) if e.code in ("RATE_LIMITED", "DISABLED")
                          else "That code didn't work. Check it, or ask for a new code.", status_code=400)
    user = p.db.scalar(select(User).where(User.tekurious_user_id == who["id"]))
    user = user or p.db.scalar(select(User).where(User.phone == who["phone"]))
    method = "phone"
    if user is None:
        if not flow.get("consented"):  # numbers new to us always pass the sign-up page first; be safe anyway
            return _with_flow(p.render("auth/phone_signup.html", phone=flow["phone"], form={}), flow)
        user = User(phone=who["phone"], tekurious_user_id=who["id"], name=flow.get("name") or who.get("displayName"),
                    password_hash=auth_api.NO_PASSWORD, is_minor=False, guardian_consent_status="not_required")
        p.db.add(user)
        p.db.flush()
        p.db.add(ConsentRecord(user_id=user.id, kind="privacy_notice", action="granted",
                               notice_version=get_settings().privacy_notice_version, method="signup_checkbox_phone",
                               details={"confirmed_18_plus": True}))
        method = "signup"
    user.tekurious_user_id = user.tekurious_user_id or who["id"]
    user.phone = user.phone or who["phone"]
    user.name = user.name or who.get("displayName")
    p.db.commit()
    record_login(p.db, user, method, p.request)
    resp = RedirectResponse("/profile" if method == "signup" else flow.get("next") or "/dashboard", status_code=303)
    auth_api._set_cookie(resp, user)
    resp.delete_cookie(FLOW_COOKIE, path="/")
    return resp
