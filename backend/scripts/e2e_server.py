"""Start a throwaway copy of the site for the browser (Playwright) tests.

Creates a fresh SQLite database through the Alembic migrations, seeds demo data, then serves on
the given port. Nothing touches the development database.

    python scripts/e2e_server.py 8766
"""
import os
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
E2E_DIR = BACKEND / ".e2e"
PORT = int(sys.argv[1] if len(sys.argv) > 1 else 8766)
shutil.rmtree(E2E_DIR, ignore_errors=True)
E2E_DIR.mkdir()
os.environ.update({
    "DATABASE_URL": f"sqlite:///{(E2E_DIR / 'e2e.db').as_posix()}",
    "STORAGE_DIR": str(E2E_DIR / "storage"),
    "RATE_LIMIT_DEFAULT": "100000", "RATE_LIMIT_AUTH": "100000", "RATE_LIMIT_ASSISTANT": "100000",
    "ANTHROPIC_API_KEY": "", "OPENROUTER_API_KEY": "", "VOYAGE_API_KEY": "", "REDIS_URL": "", "EMAIL_BACKEND": "console",
    "PLACES_PROVIDER": "none", "PUBLIC_APP_URL": f"http://127.0.0.1:{PORT}",
})
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")

import uvicorn  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.seed import seed_demo, seed_demo_accounts, seed_reference  # noqa: E402

with SessionLocal() as db:
    seed_reference(db)
    seed_demo(db)
    seed_demo_accounts(db)

uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, log_level="warning")
