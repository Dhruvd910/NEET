"""Test fixtures. Uses a throwaway SQLite DB and only synthetic, clearly-labelled data."""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="neet-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["STORAGE_DIR"] = str(_tmp / "storage")
os.environ["ANTHROPIC_API_KEY"] = ""  # assistant tests use the deterministic backend
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["RATE_LIMIT_DEFAULT"] = "100000"
os.environ["RATE_LIMIT_AUTH"] = "100000"
os.environ["REDIS_URL"] = ""
os.environ["VOYAGE_API_KEY"] = ""
os.environ["PLACES_PROVIDER"] = "none"
os.environ["EMAIL_BACKEND"] = "console"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_demo, seed_demo_accounts, seed_reference  # noqa: E402

PASSWORD = "demo-password-123"


@pytest.fixture(scope="session", autouse=True)
def database():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_reference(db)
        seed_demo(db)
        seed_demo_accounts(db)
    yield


@pytest.fixture
def db():
    with SessionLocal() as s:
        yield s


class BrowserLikeClient(TestClient):
    """Behaves like the web app: echoes the CSRF cookie in X-CSRF-Token on unsafe requests."""

    def request(self, method, url, **kwargs):
        token = self.cookies.get("neet_csrf")
        if token and method.upper() not in ("GET", "HEAD", "OPTIONS"):
            kwargs["headers"] = {**(kwargs.get("headers") or {}), "X-CSRF-Token": token}
        return super().request(method, url, **kwargs)


@pytest.fixture
def client():
    return BrowserLikeClient(app)


def login(client: TestClient, email: str) -> TestClient:
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def student(client):
    return login(client, "student@demo.test")


@pytest.fixture
def admin(client):
    return login(client, "admin@demo.test")
