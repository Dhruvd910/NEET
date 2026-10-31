"""Scheduled maintenance jobs. Run daily from cron / a scheduler:

    python -m app.maintenance purge-unconsented
    python -m app.maintenance grow-question-bank --per-section 100   # AI-written, independently checked
    python -m app.maintenance export-questions --file questions.json   # copy a question bank between databases
    python -m app.maintenance import-questions --file questions.json
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
    parser.add_argument("job", choices=["purge-unconsented", "grow-question-bank", "export-questions", "import-questions"])
    parser.add_argument("--per-section", type=int, default=100)
    parser.add_argument("--file", default="questions.json")
    args = parser.parse_args()
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
            print(f"Removed {purge_unconsented(db)} account(s).")
        elif args.job == "export-questions":
            print(f"Exported {export_questions(db, args.file)} question(s) to {args.file}.")
        elif args.job == "import-questions":
            added, skipped = import_questions(db, args.file)
            print(f"Imported {added} question(s); skipped {skipped} already present or for unknown chapters.")


if __name__ == "__main__":
    main()
