"""Security & privacy hardening: CSRF, shared rate limiting, guardian consent, retention, prod config."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import app
from app.maintenance import purge_unconsented
from app.models import ConsentRecord, User
from app.security import RateLimiter, RedisRateLimiter, hash_password
from app.services.email import outbox
from tests.conftest import PASSWORD


def test_csrf_required_for_cookie_sessions():
    raw = TestClient(app)  # does not echo the CSRF cookie
    r = raw.post("/api/auth/login", json={"email": "student@demo.test", "password": PASSWORD})
    assert r.status_code == 200 and raw.cookies.get("neet_csrf")
    r = raw.put("/api/profile", json={"display_name": "Demo Student"})
    assert r.status_code == 403 and "CSRF" in r.json()["detail"]
    r = raw.put("/api/profile", json={"display_name": "Demo Student"}, headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403
    r = raw.put("/api/profile", json={"display_name": "Demo Student"},
                headers={"X-CSRF-Token": raw.cookies.get("neet_csrf")})
    assert r.status_code == 200
    assert raw.get("/api/profile").status_code == 200  # safe methods need no token


def test_csrf_cookie_is_reissued_for_old_sessions():
    raw = TestClient(app)
    raw.post("/api/auth/login", json={"email": "student@demo.test", "password": PASSWORD})
    raw.cookies.delete("neet_csrf")
    r = raw.get("/api/auth/me")
    assert r.status_code == 200 and "neet_csrf" in r.headers.get("set-cookie", "")


class FakeRedis:
    def __init__(self, fail=False):
        self.data, self.fail = {}, fail

    def pipeline(self):
        outer = self

        class Pipe:
            def __init__(self):
                self.ops = []

            def incr(self, k):
                self.ops.append(("incr", k))

            def expire(self, k, s):
                self.ops.append(("expire", k))

            def execute(self):
                if outer.fail:
                    raise ConnectionError("redis down")
                out = []
                for op, k in self.ops:
                    if op == "incr":
                        outer.data[k] = outer.data.get(k, 0) + 1
                        out.append(outer.data[k])
                    else:
                        out.append(True)
                return out
        return Pipe()


def test_redis_rate_limiter_is_shared_between_instances():
    shared = FakeRedis()
    worker_a, worker_b = RedisRateLimiter(shared), RedisRateLimiter(shared)
    assert all(worker_a.check("auth:1.2.3.4", 3) for _ in range(2))
    assert worker_b.check("auth:1.2.3.4", 3)          # third request, other worker
    assert not worker_a.check("auth:1.2.3.4", 3)      # fourth is refused everywhere
    assert worker_b.check("auth:5.6.7.8", 3)          # other clients unaffected


def test_redis_outage_falls_back_to_local_limits():
    limiter = RedisRateLimiter(FakeRedis(fail=True), fallback=RateLimiter())
    assert limiter.check("k", 1) and not limiter.check("k", 1)


def _register_minor(client):
    email = f"minor-{uuid.uuid4().hex[:8]}@example.test"
    r = client.post("/api/auth/register", json={"email": email, "password": PASSWORD, "is_minor": True,
                                               "guardian_email": "parent@example.test", "accept_privacy_notice": True})
    assert r.status_code == 201
    token = outbox[-1]["body"].split("token=")[1].split()[0]
    return email, token


def test_minor_is_locked_until_guardian_confirms(client, db):
    email, token = _register_minor(client)
    assert outbox[-1]["to"] == "parent@example.test"
    assert client.get("/api/profile").status_code == 403
    assert client.get("/api/auth/me").json()["guardian_consent_status"] == "pending"
    assert client.get("/api/auth/me/export").status_code == 200  # data rights always available

    info = client.get(f"/api/auth/guardian-consent/{token}").json()
    assert info["status"] == "pending" and "@" in info["student_email"] and info["student_email"] != email
    bad = client.post(f"/api/auth/guardian-consent/{token}", json={
        "decision": "approve", "guardian_name": "P", "relationship": "parent", "confirm_is_guardian": True})
    assert bad.status_code == 422  # name too short
    r = client.post(f"/api/auth/guardian-consent/{token}", json={
        "decision": "approve", "guardian_name": "Parent Name", "relationship": "mother", "confirm_is_guardian": True})
    assert r.status_code == 200 and r.json()["status"] == "verified"
    assert client.get("/api/profile").status_code in (200, 404)
    assert client.get(f"/api/auth/guardian-consent/{token}").status_code == 404  # single use

    user = db.scalar(select(User).where(User.email == email))
    kinds = [(c.kind, c.action) for c in db.scalars(select(ConsentRecord).where(ConsentRecord.user_id == user.id))]
    assert ("privacy_notice", "granted") in kinds and ("guardian_consent", "granted") in kinds


def test_guardian_can_decline_and_links_expire(client, db):
    email, token = _register_minor(client)
    r = client.post(f"/api/auth/guardian-consent/{token}", json={
        "decision": "decline", "guardian_name": "Parent Name", "relationship": "father", "confirm_is_guardian": True})
    assert r.json()["status"] == "declined"
    assert client.get("/api/profile").status_code == 403

    email2, token2 = _register_minor(client)
    u = db.scalar(select(User).where(User.email == email2))
    u.guardian_token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert client.get(f"/api/auth/guardian-consent/{token2}").status_code == 404
    assert client.post("/api/auth/guardian-consent-resend").json()["ok"]  # client is signed in as email2


def test_purge_removes_unconsented_minors_after_retention(db):
    now = datetime.now(timezone.utc)
    old = User(email=f"old-{uuid.uuid4().hex[:6]}@example.test", password_hash=hash_password("x" * 10),
               is_minor=True, guardian_consent_status="pending", created_at=now - timedelta(days=30))
    fresh = User(email=f"new-{uuid.uuid4().hex[:6]}@example.test", password_hash=hash_password("x" * 10),
                 is_minor=True, guardian_consent_status="pending", created_at=now)
    ok = User(email=f"ok-{uuid.uuid4().hex[:6]}@example.test", password_hash=hash_password("x" * 10),
              is_minor=True, guardian_consent_status="verified", created_at=now - timedelta(days=30))
    db.add_all([old, fresh, ok])
    db.commit()
    ids = (old.id, fresh.id, ok.id)
    purge_unconsented(db, now)
    remaining = set(db.scalars(select(User.id).where(User.id.in_(ids))))
    assert remaining == {fresh.id, ok.id}


def test_production_refuses_insecure_settings():
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(_env_file=None, env="production")
    s = Settings(_env_file=None, env="production", jwt_secret="x" * 40, cookie_secure=True,
                 database_url="postgresql+psycopg://u:p@db/neet", email_backend="smtp")
    assert s.env == "production"


def test_health_and_readiness(client):
    assert client.get("/api/health").json()["status"] == "ok"
    r = client.get("/api/ready")
    assert r.status_code == 200 and r.json()["database"] == "ok"
    assert r.headers.get("x-request-id")
