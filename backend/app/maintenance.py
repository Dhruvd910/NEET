"""Scheduled maintenance jobs. Run daily from cron / a scheduler:

    python -m app.maintenance purge-unconsented
    python -m app.maintenance grow-question-bank --per-section 100   # AI-written, independently checked
    python -m app.maintenance export-questions --file questions.json   # copy a question bank between databases
    python -m app.maintenance import-questions --file questions.json
    python -m app.maintenance import-colleges      # official NMC list of MBBS colleges (--offline: saved snapshot)
    python -m app.maintenance locate-colleges      # map location + website from Wikidata / OpenStreetMap
    python -m app.maintenance check-websites       # drop websites that do not answer
    python -m app.maintenance refresh-nearby-all   # surroundings from OpenStreetMap (slow; resumable)
    python -m app.maintenance create-admin --email you@example.com   # new admin with a password
    python -m app.maintenance make-admin --email you@gmail.com       # make an existing (e.g. Google) account admin
"""
import argparse
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import User

log = logging.getLogger(__name__)


def purge_unconsented(db: Session, now: datetime | None = None) -> int:
    """Delete minors' accounts whose guardian declined, or never answered within the retention window."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=get_settings().unconsented_minor_retention_days)
    users = db.scalars(select(User).where(
        User.is_minor.is_(True), User.guardian_consent_status.in_(["pending", "declined"]))).all()
    removed = 0
    for u in users:
        created = u.created_at if u.created_at.tzinfo else u.created_at.replace(tzinfo=timezone.utc)
        if u.guardian_consent_status == "declined" or created < cutoff:
            db.delete(u)
            removed += 1
    db.commit()
    log.info("purge-unconsented: removed %d account(s)", removed)
    return removed


def purge_login_history(db: Session, now: datetime | None = None) -> int:
    """Sign-in history is kept for LOGIN_HISTORY_DAYS only (stated in the sign-up notice)."""
    from sqlalchemy import delete

    from app.models import LoginEvent
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=get_settings().login_history_days)
    n = db.execute(delete(LoginEvent).where(LoginEvent.at < cutoff)).rowcount
    db.commit()
    return n


EXPORT_FIELDS = ("subject", "topic", "difficulty", "stem", "options", "correct_index", "explanation", "review_status",
                 "content_hash", "qformat", "generated_by", "checked_by", "source_name")


def export_questions(db: Session, path: str) -> int:
    """Write served questions (not drafts, flagged or retired ones) to a JSON file, keyed by chapter code."""
    from app.models import Question
    from app.services.exams import SERVED
    rows = [{"chapter_code": q.chapter.code, **{f: getattr(q, f) for f in EXPORT_FIELDS}}
            for q in db.scalars(select(Question).where(Question.review_status.in_(SERVED)))]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"format": "neet-compass-questions/1", "questions": rows}, f, ensure_ascii=False)
    return len(rows)


def import_questions(db: Session, path: str) -> tuple[int, int]:
    """Add questions from export_questions. Existing questions (same content) are skipped. Returns (added, skipped)."""
    from app.models import Question, SyllabusChapter, VerificationStatus
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("format") != "neet-compass-questions/1":
        raise SystemExit("Not a question export from this app.")
    chapters = {c.code: c.id for c in db.scalars(select(SyllabusChapter))}
    have = set(db.scalars(select(Question.content_hash)))
    added = skipped = 0
    for row in data["questions"]:
        if row["content_hash"] in have or row["chapter_code"] not in chapters:
            skipped += 1
            continue
        fields = {f: row[f] for f in EXPORT_FIELDS}
        verified = fields["review_status"] == "reviewed"
        db.add(Question(chapter_id=chapters[row["chapter_code"]], **fields,
                        verification_status=VerificationStatus.verified if verified else VerificationStatus.unverified))
        have.add(row["content_hash"])
        added += 1
    db.commit()
    return added, skipped


def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("job", choices=["purge-unconsented", "grow-question-bank", "export-questions", "import-questions",
                                        "import-colleges", "locate-colleges", "check-websites", "refresh-nearby-all",
                                        "create-admin", "make-admin"])
    parser.add_argument("--per-section", type=int, default=100)
    parser.add_argument("--file", default="questions.json")
    parser.add_argument("--offline", action="store_true", help="import-colleges: use the saved NMC snapshot")
    parser.add_argument("--limit", type=int, default=None, help="locate-colleges / refresh-nearby-all: at most N colleges")
    parser.add_argument("--email", help="create-admin: the admin's email (you are asked for the password)")
    args = parser.parse_args()
    if args.job in ("import-colleges", "locate-colleges", "check-websites", "refresh-nearby-all", "create-admin",
                    "make-admin"):
        return catalogue_job(args)
    if args.job == "grow-question-bank":
        from sqlalchemy import func

        from app.models import Question
        from app.services import question_gen
        from app.services.exams import SECTIONS, SERVED
        if not question_gen.enabled():
            raise SystemExit("Set OPENROUTER_API_KEY (and QUESTION_GEN_ENABLED=true) first.")
        question_gen.top_up({s: args.per_section for s in SECTIONS}, SessionLocal)
        with SessionLocal() as db:
            counts = dict(db.execute(select(Question.subject, func.count()).where(Question.review_status.in_(SERVED))
                                     .group_by(Question.subject)).all())
        print(f"Question bank (served questions per section): {counts}")
        return
    with SessionLocal() as db:
        if args.job == "purge-unconsented":
            print(f"Removed {purge_unconsented(db)} account(s) and {purge_login_history(db)} old sign-in record(s).")
        elif args.job == "export-questions":
            print(f"Exported {export_questions(db, args.file)} question(s) to {args.file}.")
        elif args.job == "import-questions":
            added, skipped = import_questions(db, args.file)
            print(f"Imported {added} question(s); skipped {skipped} already present or for unknown chapters.")


def catalogue_job(args):
    """Real college catalogue (services/real_colleges.py) and the first real admin account."""
    from app.services import real_colleges as rc
    with SessionLocal() as db:
        if args.job == "import-colleges":
            snap = (json.loads((rc.DATA / "nmc_mbbs.json").read_text(encoding="utf-8")) if args.offline
                    else rc.fetch_nmc())
            print(f"NMC list fetched {snap['fetched']}: {len(snap['rows'])} colleges.")
            print(f"Imported: {rc.import_nmc(db, snap)}", flush=True)
            print(f"NMC college details: {rc.fetch_nmc_details(db, snap, args.limit)}", flush=True)
        elif args.job == "locate-colleges":
            print(f"OpenStreetMap (bulk match): {rc.match_osm(db)}", flush=True)
            try:
                print(f"Wikidata: {rc.enrich_from_wikidata(db, args.limit)}", flush=True)
            except Exception as e:  # noqa: BLE001 — Wikidata is optional; the OpenStreetMap search still runs
                print(f"Wikidata stopped early ({e}); run again later to continue.", flush=True)
            print(f"OpenStreetMap (search, slow): {rc.enrich_locations(db, args.limit)}", flush=True)
        elif args.job == "check-websites":
            print(f"Websites: {rc.verify_websites(db)}")
        elif args.job == "refresh-nearby-all":
            print(f"Nearby places: {refresh_nearby_all(db, args.limit)}")
        elif args.job == "create-admin":
            print(create_admin(db, args.email))
        elif args.job == "make-admin":
            print(make_admin(db, args.email))


def refresh_nearby_all(db, limit=None) -> dict:
    """Surroundings for every located college from OpenStreetMap (Overpass), slowly, to respect its fair-use policy.
    Colleges that already have places are skipped, so the job can be stopped and resumed."""
    import time

    from app.models import College, NearbyPlace
    from app.services import places
    todo = db.scalars(select(College).where(College.is_demo.is_(False), College.latitude.is_not(None),
                                            ~College.id.in_(select(NearbyPlace.college_id)))).all()[:limit]
    done = failed = 0
    for i, c in enumerate(todo, 1):
        for attempt in range(3):
            try:
                rows = places.refresh_nearby(db, c, fetch=places.fetch_overpass)
                done += 1
                print(f"  [{i}/{len(todo)}] {c.name}: {len(rows)} places", flush=True)
                break
            except places.PlacesError as e:
                db.rollback()
                if attempt == 2:
                    failed += 1
                    print(f"  [{i}/{len(todo)}] {c.name}: failed ({e})", flush=True)
                time.sleep(30 * (attempt + 1))  # busy server: back off
        time.sleep(3)
    return {"refreshed": done, "failed": failed, "remaining": len(todo) - done - failed}


def create_admin(db, email: str | None) -> str:
    """The first real admin. The password is typed in the terminal and never shown or stored in plain text."""
    import getpass

    from app.models import Role, User
    from app.security import hash_password
    email = (email or input("Admin email: ")).strip().lower()
    password = getpass.getpass("Password (min. 12 characters): ")
    if len(password) < 12 or password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords must match and be at least 12 characters.")
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, password_hash=hash_password(password), role=Role.admin)
        db.add(user)
    else:
        user.password_hash, user.role = hash_password(password), Role.admin
    db.commit()
    return f"{email} is now an admin."


def make_admin(db, email: str | None) -> str:
    """Makes an existing account (for example one that signs in with Google) an admin."""
    from app.models import Role, User
    if not email:
        raise SystemExit("Give the account's email: make-admin --email you@example.com")
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise SystemExit(f"No account with {email}. Sign up on the site first, then run this again.")
    user.role = Role.admin
    db.commit()
    return f"{user.email} is now an admin."


if __name__ == "__main__":
    main()
