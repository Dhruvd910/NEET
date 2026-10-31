"""Nightly backup: PostgreSQL dump + stored source files, for the single-host Docker deployment.

Run from the repository root via cron, e.g.
    15 2 * * * cd /srv/neet && python3 deploy/backup.py >> /var/log/neet-backup.log 2>&1

    BACKUP_DIR   where backups go (default /var/backups/neet)
    KEEP_DAYS    delete backups older than this many days (default 14)

Copy BACKUP_DIR off the host (object storage with encryption at rest), and test a restore monthly.
Uses only the Python standard library, so it runs on the host without installing anything.
"""
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

COMPOSE = ["docker", "compose", "-f", "deploy/docker-compose.prod.yml", "--env-file", "deploy/.env"]


def dump(command: list[str], target: Path) -> None:
    """Streams a command's output into a file; a failed command leaves no partial backup behind."""
    with target.open("wb") as out:
        result = subprocess.run(COMPOSE + command, stdout=out)
    if result.returncode != 0:
        target.unlink(missing_ok=True)
        raise SystemExit(f"backup step failed: {' '.join(command)}")


def main() -> None:
    backup_dir = Path(os.environ.get("BACKUP_DIR", "/var/backups/neet"))
    keep_days = int(os.environ.get("KEEP_DAYS", "14"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir.mkdir(parents=True, exist_ok=True)

    dump(["exec", "-T", "db", "pg_dump", "-U", "neet", "-d", "neet", "--format=custom"], backup_dir / f"db-{stamp}.dump")
    dump(["exec", "-T", "api", "tar", "-C", "/data", "-czf", "-", "storage"], backup_dir / f"storage-{stamp}.tar.gz")

    # Retention: deleted accounts disappear from backups after KEEP_DAYS (state this in the privacy notice).
    cutoff = time.time() - keep_days * 86400
    for f in backup_dir.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink()
    print(f"backup {stamp} ok")


if __name__ == "__main__":
    main()
