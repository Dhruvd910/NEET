"""Container start: migrate, optionally seed, then serve the site and API.

    RUN_MIGRATIONS=0          skip `alembic upgrade head` (when several replicas share one database)
    SEED_ON_START=reference   add reference data (courses, authorities, syllabus, info pages) if missing
    SEED_ON_START=demo        reference data + the clearly-labelled DEMO colleges, questions and accounts
                              (either value also imports data/question_bank.json, skipping questions already present)
    PORT                      port to listen on (free hosts such as Render set this; default 8000)
    WEB_CONCURRENCY           number of server processes (default 1)
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], cwd=HERE, check=True)


def main() -> None:
    if os.environ.get("RUN_MIGRATIONS", "1") == "1":
        from alembic import command
        from alembic.config import Config
        command.upgrade(Config(str(HERE / "alembic.ini")), "head")

    seed = os.environ.get("SEED_ON_START", "")
    if seed == "reference":
        run("-m", "app.seed", "--no-demo", "--if-empty")
    elif seed == "demo":
        run("-m", "app.seed", "--if-empty")
    elif seed:
        sys.exit(f"Unknown SEED_ON_START={seed} (use reference or demo)")

    # Ship-with question bank (AI-written, independently checked). Already-present questions are skipped.
    bank = HERE / "data" / "question_bank.json"
    if seed and bank.exists():
        run("-m", "app.maintenance", "import-questions", "--file", str(bank))

    # The server runs in this process, so it receives the platform's stop signal directly.
    import uvicorn
    os.chdir(HERE)
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")),
                workers=int(os.environ.get("WEB_CONCURRENCY", "1")), proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
