"""Browser tests (Playwright for Python) against a throwaway copy of the site.

    python -m playwright install chromium   # once
    python -m pytest e2e

The site runs from scripts/e2e_server.py on its own port with a fresh, seeded SQLite database, so these
tests never touch the development database.
"""
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

BACKEND = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("E2E_PORT", "8766"))
BASE = f"http://127.0.0.1:{PORT}"
PASSWORD = os.environ.get("E2E_PASSWORD", "demo-password-123")  # SEED_DEMO_PASSWORD default
OUTBOX = BACKEND / ".e2e" / "storage" / "outbox"

expect.set_options(timeout=10_000)


@pytest.fixture(scope="session")
def base_url():
    proc = subprocess.Popen([sys.executable, str(BACKEND / "scripts" / "e2e_server.py"), str(PORT)], cwd=BACKEND)
    deadline = time.time() + 120
    while True:
        try:
            urllib.request.urlopen(f"{BASE}/api/ready", timeout=2)
            break
        except OSError:
            if proc.poll() is not None or time.time() > deadline:
                proc.kill()
                raise RuntimeError("The e2e server did not start.")
            time.sleep(0.5)
    yield BASE
    proc.terminate()
    proc.wait(timeout=10)


def sign_in(page: Page, email: str):
    page.goto("/login")
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(f"{BASE}/dashboard")
    expect(page.get_by_role("button", name="Sign out")).to_be_visible()


def new_student(page: Page):
    page.goto("/register")
    page.get_by_label("Email", exact=True).fill(f"e2e-{time.time_ns()}@example.test")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_label("No", exact=True).check()
    page.get_by_label(re.compile("I have read the privacy")).check()
    page.get_by_role("button", name="Create account").click()
    expect(page).to_have_url(f"{BASE}/profile")


def latest_email() -> str:
    """Latest email written by the console email backend, e.g. the guardian-consent link."""
    files = sorted(OUTBOX.iterdir())
    return files[-1].read_text(encoding="utf-8")
