"""Google sign-in and the admin's sign-in history. Google's token endpoint is faked; everything else is real."""
import time
import urllib.parse

import jwt
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import LoginEvent, Role, User
from app.security import ip_prefix
from app.services import google_auth

CLIENT_ID = "test-client.apps.googleusercontent.com"


@pytest.fixture
def google(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(s, "google_client_secret", "test-secret")
    identity = {"sub": "google-123", "email": "asha.google@example.test", "name": "Asha Rao", "email_verified": True}

    class FakeResponse:
        status_code = 200

        def __init__(self, token):
            self._token = token

        def json(self):
            return {"id_token": self._token}

    def fake_post(url, data, timeout):
        assert url == google_auth.TOKEN_URL and data["code_verifier"] and data["client_secret"] == "test-secret"
        claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "exp": int(time.time()) + 300,
                  "nonce": fake_post.nonce, **identity}
        return FakeResponse(jwt.encode(claims, "unused", algorithm="HS256"))

    monkeypatch.setattr(google_auth.httpx, "post", fake_post)
    return identity, fake_post


def sign_in_with_google(client, fake_post, state_override=None):
    r = client.get("/auth/google?next=/dashboard", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(google_auth.AUTH_URL)
    params = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)
    assert params["code_challenge_method"] == ["S256"] and params["scope"] == ["openid email profile"]
    fake_post.nonce = params["nonce"][0]
    state = state_override or params["state"][0]
    return client.get(f"/auth/google/callback?code=abc&state={state}", follow_redirects=False)


def test_button_hidden_until_configured(client):
    assert "Continue with Google" not in client.get("/login").text
    assert client.get("/auth/google").status_code == 503


def test_new_google_user_answers_age_question_then_is_signed_in(client, google, db):
    identity, fake_post = google
    r = sign_in_with_google(client, fake_post)
    assert r.headers["location"] == "/register/google"
    page = client.get("/register/google")
    assert "Asha Rao" in page.text and identity["email"] in page.text
    assert client.post("/register/google", data={"minor": "no", "name": "Asha Rao"}).status_code == 400  # no privacy
    assert client.post("/register/google", data={"minor": "no", "privacy": "on", "name": " "}).status_code == 400
    r = client.post("/register/google", data={"minor": "no", "privacy": "on", "name": "Asha Rao"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/profile"
    user = db.scalar(select(User).where(User.email == identity["email"]))
    assert user.google_sub == "google-123" and user.name == "Asha Rao" and user.login_count == 1
    # A Google-only account has no password that could ever match.
    bad = client.post("/api/auth/login", json={"email": identity["email"], "password": "no-password"})
    assert bad.status_code == 401 and "Google" in bad.json()["detail"]

    client.cookies.clear()
    r = sign_in_with_google(client, fake_post)  # returning user goes straight in
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"
    db.expire_all()
    assert db.scalar(select(User).where(User.email == identity["email"])).login_count == 2


def test_existing_email_account_is_linked(client, google, db):
    identity, fake_post = google
    identity.update(sub="google-student", email="student@demo.test")
    r = sign_in_with_google(client, fake_post)
    assert r.headers["location"] == "/dashboard"
    assert db.scalar(select(User).where(User.email == "student@demo.test")).google_sub == "google-student"


def test_forged_state_is_rejected(client, google):
    _, fake_post = google
    r = sign_in_with_google(client, fake_post, state_override="not-the-state")
    assert r.status_code == 400 and "expired" in r.text


def test_password_sign_in_is_recorded_and_admin_sees_it(client, db):
    client.post("/login", data={"email": "student@demo.test", "password": "demo-password-123"},
                headers={"User-Agent": "TestBrowser/1.0"})
    event = db.scalars(select(LoginEvent).order_by(LoginEvent.id.desc())).first()
    assert event.method == "password" and event.user_agent == "TestBrowser/1.0"
    client.post("/logout")
    client.cookies.clear()
    client.post("/login", data={"email": "admin@demo.test", "password": "demo-password-123"})
    page = client.get("/admin?tab=users")
    assert page.status_code == 200 and "Sign-in log" in page.text and "student@demo.test" in page.text
    assert client.get("/admin?tab=users&q=student", headers={"HX-Request": "true"}).status_code == 200


def test_admin_can_change_roles_but_not_their_own(admin, db):
    student = db.scalar(select(User).where(User.email == "student@demo.test"))
    me = db.scalar(select(User).where(User.email == "admin@demo.test"))
    hx = {"HX-Request": "true"}
    assert admin.post("/admin/users/role", data={"id": me.id, "role": "student"}, headers=hx).status_code == 422
    assert admin.post("/admin/users/role", data={"id": student.id, "role": "admin"}, headers=hx).status_code == 200
    db.expire_all()
    assert db.get(User, student.id).role == Role.admin
    admin.post("/admin/users/role", data={"id": student.id, "role": "student"}, headers=hx)


def test_ip_is_shortened():
    assert ip_prefix("203.0.113.57") == "203.0.113.x"
    assert ip_prefix("2001:db8:1:2:3:4:5:6") == "2001:db8:1:2::x"
    assert ip_prefix("unknown") is None


def test_dashboard_greets_with_the_sign_up_name(client, google):
    identity, fake_post = google
    identity.update(sub="google-greeting", email="asha.greeting@example.test", name="Asha Rao")
    assert sign_in_with_google(client, fake_post).headers["location"] == "/register/google"
    client.post("/register/google", data={"minor": "no", "privacy": "on", "name": "Asha R."})
    assert "Hello, future Dr. Asha R." in client.get("/dashboard").text
    assert 'value="Asha R."' in client.get("/profile").text  # profile name pre-filled
