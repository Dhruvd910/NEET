"""Phone sign-in through Tekurious AI-Auth. The service is faked with the responses seen from the live API."""
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import ConsentRecord, LoginEvent, User
from app.services import phone_auth
from app.web.routes_phone import FLOW_COOKIE


class FakeTekurious:
    """Remembers codes per reqId like the real service (one use each) and which numbers already have an account."""

    def __init__(self):
        self.known = {"+919800000001": {"id": "tk-existing", "displayName": "Existing Student"}}
        self.sent, self.calls = {}, []

    def __call__(self, method, path, json=None, token=None):
        self.calls.append((method, path, json))
        if path == "/v1/countries/allowed":
            return {"items": [{"code": "IN", "name": "India", "dialCode": "+91", "flag": "IN"}]}
        if path == "/v1/otp/send":
            req = f"stub-{len(self.sent)}"
            self.sent[req] = {"phone": json["phone"], "signup": json.get("isAdult") is True, "name": json.get("displayName")}
            return {"reqId": req}
        if path == "/v1/otp/verify":
            entry = self.sent.pop(json["reqId"], None)
            if entry is None:
                raise phone_auth.PhoneAuthError("This code expired — start the login again.", code="410")
            if json["otp"] != "123456":
                raise phone_auth.PhoneAuthError("Invalid code", code="400")
            if entry["phone"] not in self.known:
                if not entry["signup"]:
                    raise phone_auth.PhoneAuthError("Sign up is required", code="SIGNUP_REQUIRED")
                self.known[entry["phone"]] = {"id": f"tk-{entry['phone'][-4:]}", "displayName": entry["name"]}
            self.last = entry["phone"]
            return {"userId": self.known[entry["phone"]]["id"], "phone": entry["phone"], "sessionToken": "s", "refreshToken": "r"}
        if path == "/v1/me":
            u = self.known[self.last]
            return {"id": u["id"], "displayName": u["displayName"], "phone": self.last, "disabled": False}
        raise AssertionError(path)


@pytest.fixture
def tek(monkeypatch):
    monkeypatch.setattr(get_settings(), "tekurious_api_key", "tek_test")
    monkeypatch.setattr(get_settings(), "otp_resend_seconds", 0)
    monkeypatch.setattr(get_settings(), "phone_allow_stub", True)  # the fake hands out "stub-" request ids
    fake = FakeTekurious()
    monkeypatch.setattr(phone_auth, "_call", fake)
    phone_auth._countries = (0.0, [])
    return fake


def test_phone_form_shown_only_when_configured(client, tek, monkeypatch):
    assert "Send code" in client.get("/login").text
    monkeypatch.setattr(get_settings(), "tekurious_api_key", "")
    assert "Send code" not in client.get("/login").text


def test_normalize():
    assert phone_auth.normalize("+91", "98765 43210") == "+919876543210"
    assert phone_auth.normalize("+91", "098765-43210") == "+919876543210"
    assert phone_auth.normalize("+91", "+91 98765 43210") == "+919876543210"
    assert phone_auth.normalize("+91", "919876543210") == "+919876543210"
    assert not phone_auth.valid(phone_auth.normalize("+91", "123"))


def test_new_number_signs_up_with_name_and_confirmations(client, tek, db):
    r = client.post("/login/phone", data={"dial": "+91", "number": "98111 22233"})
    assert "Welcome to NEET Compass" in r.text and FLOW_COOKIE in r.cookies
    assert not [c for c in tek.calls if c[1] == "/v1/otp/send"]  # no SMS until the sign-up questions are answered
    r = client.post("/login/phone/signup", data={"name": "Riya Sharma", "terms": "on"})
    assert r.status_code == 400 and "18 or over" in r.text  # 18+ not confirmed
    r = client.post("/login/phone/signup", data={"name": "Riya Sharma", "adult": "on", "terms": "on"})
    assert "Enter the code" in r.text
    assert tek.calls[-1][2] == {"phone": "+919811122233", "displayName": "Riya Sharma", "isAdult": True,
                                "acceptTerms": True, "acceptPrivacy": True}
    assert client.post("/login/phone/verify", data={"otp": "000000"}).status_code == 400
    # a wrong code used up that reqId, as the real service does: ask for a new one
    client.post("/login/phone/resend")
    r = client.post("/login/phone/verify", data={"otp": "123 456"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/profile"
    user = db.scalar(select(User).where(User.phone == "+919811122233"))
    assert user.name == "Riya Sharma" and user.email is None and user.tekurious_user_id == "tk-2233"
    assert db.scalar(select(ConsentRecord).where(ConsentRecord.user_id == user.id)).method == "signup_checkbox_phone"
    assert db.scalar(select(LoginEvent).where(LoginEvent.user_id == user.id)).method == "signup"
    assert client.get("/dashboard").status_code == 200  # signed in


def test_returning_number_goes_straight_to_code(client, tek, db):
    db.add(User(phone="+919800000001", tekurious_user_id="tk-existing", name="Existing Student", password_hash="no-password"))
    db.commit()
    r = client.post("/login/phone", data={"dial": "+91", "number": "9800000001", "next": "/practice"})
    assert "Enter the code" in r.text and tek.calls[-1][2] == {"phone": "+919800000001"}
    r = client.post("/login/phone/verify", data={"otp": "123456"}, follow_redirects=False)
    assert r.headers["location"] == "/practice"
    assert db.scalar(select(User).where(User.phone == "+919800000001")).login_count == 1


def test_bad_number_and_rate_limit_messages(client, tek, monkeypatch):
    assert "country code" in client.post("/login/phone", data={"dial": "+91", "number": "12"}).text

    def limited(*_a, **_k):
        raise phone_auth.PhoneAuthError("Too many codes requested. Please wait 59 minute(s) and try again.",
                                        code="RATE_LIMITED", retry_after=3552)
    monkeypatch.setattr(phone_auth, "send_code", limited)
    client.post("/login/phone", data={"dial": "+91", "number": "9822233344"})
    r = client.post("/login/phone/signup", data={"name": "Kabir", "adult": "on", "terms": "on"})
    assert r.status_code == 400 and "Too many codes" in r.text


def test_verify_without_a_started_flow_is_refused(client, tek):
    r = client.post("/login/phone/verify", data={"otp": "123456"})
    assert r.status_code == 400 and "took too long" in r.text


def test_phone_account_cannot_use_password_login(client, db):
    db.add(User(phone="+919800000009", email="phone.only@example.test", password_hash="no-password"))
    db.commit()
    r = client.post("/api/auth/login", json={"email": "phone.only@example.test", "password": "no-password"})
    assert r.status_code == 401 and "phone number" in r.json()["detail"]


def test_test_mode_codes_are_refused_unless_allowed(client, tek, monkeypatch):
    """In the service's test mode a fixed code works for any number, so it must not be usable on a real site."""
    monkeypatch.setattr(get_settings(), "phone_allow_stub", False)
    client.post("/login/phone", data={"dial": "+91", "number": "9833344455"})
    r = client.post("/login/phone/signup", data={"name": "Meera", "adult": "on", "terms": "on"})
    assert r.status_code == 400 and "switched on yet" in r.text


def test_test_mode_notice_shows_the_code(client, tek):
    assert "for every number" in client.get("/login").text  # tek fixture allows test codes
    client.post("/login/phone", data={"dial": "+91", "number": "9844455566"})
    r = client.post("/login/phone/signup", data={"name": "Dev", "adult": "on", "terms": "on"})
    assert "Testing mode" in r.text and "123456" in r.text
