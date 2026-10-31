"""Timed practice tests in the NEET-UG format.

- **No repeats:** a student is only ever given questions they have never seen in any earlier test.
  When their unseen pool runs low, new questions are written and independently checked in the
  background (services/question_gen.py), and the paper is built once enough are ready.
- **NEET-like paper:** questions in each section are spread across chapters in proportion to the
  syllabus, Physics → Chemistry → Botany → Zoology, numbered 1–180.
- **Exam-day flow:** a paper is prepared first ("ready": booklet code and roll number assigned, questions
  hidden), and the clock only starts when the student opens the booklet.
- Correct answers never leave the server until the attempt is submitted.
- Every answer is saved as it is given, so a refresh or dropped connection loses nothing.
- The deadline is enforced on the server (plus a short grace period for network delay); an attempt
  that runs out of time is submitted automatically the next time it is touched.
- "Strict OMR" mimics the real answer sheet: once a bubble is filled it cannot be changed.
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    ExamAttempt, ExamAttemptItem, MockTest, MockTestSubjectScore, Question, QuestionReport, SyllabusChapter, User,
)

SECTIONS = ["Physics", "Chemistry", "Botany", "Zoology"]
SERVED = ("sample", "ai_checked", "reviewed")
GRACE_SECONDS = 30
BOOKLET_CODES = ["Q1", "Q2", "Q3", "Q4", "R1", "R2", "R3", "R4", "S1", "S2", "S3", "S4"]
NEET_PATTERN = {
    "name": "NEET-UG pattern (as in the NEET-UG 2025 Information Bulletin)",
    "sections": [{"name": s, "questions": 45} for s in SECTIONS],
    "total_questions": 180,
    "duration_minutes": 180,
    "marks_correct": 4,
    "marks_wrong": -1,
    "marks_unanswered": 0,
    "exam_time": "2:00 PM – 5:00 PM",
    "verify_note": "NTA can change the pattern every year. Check the current Information Bulletin.",
    "format_note": "The real exam is pen-and-paper: a printed question booklet and an OMR answer sheet "
                   "marked with a ball-point pen. Answers on the OMR sheet cannot be changed.",
}
MODES = {"full", "mini", "subject", "chapter", "weak"}
REPORT_REASONS = {"wrong_answer", "unclear", "out_of_syllabus", "typo", "other"}
HIDE_AFTER_REPORTS = 2


class ExamError(ValueError):
    pass


class PaperNotReady(ExamError):
    """Not enough never-seen questions yet. `needed` is per subject; generation has been started if possible."""

    def __init__(self, needed: dict[str, int], generating: bool):
        self.needed, self.generating = needed, generating
        msg = ("Preparing fresh questions you haven't seen before: " + ", ".join(f"{n} {s}" for s, n in needed.items())
               + ". This takes a few minutes." if generating else
               "You have already seen every available question for this choice, and new questions can't be generated "
               "right now. Try another subject or chapter, or ask an admin to add questions.")
        super().__init__(msg)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def bank_counts(db: Session) -> dict:
    rows = db.execute(select(Question.subject, Question.review_status, func.count())
                      .where(Question.review_status.in_(SERVED)).group_by(Question.subject, Question.review_status)).all()
    out = {s: {"sample": 0, "ai_checked": 0, "reviewed": 0} for s in SECTIONS}
    for subject, status, n in rows:
        out.setdefault(subject, {"sample": 0, "ai_checked": 0, "reviewed": 0})[status] = n
    return out


def _seen_ids(user_id: int):
    return select(ExamAttemptItem.question_id).join(ExamAttempt).where(ExamAttempt.user_id == user_id)


def _unseen(db: Session, user_id: int, *where) -> list[Question]:
    return list(db.scalars(select(Question).where(
        Question.review_status.in_(SERVED), Question.id.not_in(_seen_ids(user_id)), *where)))


def _blueprint_pick(pool: list[Question], n: int, rng: random.Random) -> list[Question]:
    """Pick n questions spread over chapters in proportion to their syllabus size (NEET-like coverage),
    with Class 11 and Class 12 both represented."""
    by_chapter: dict[int, list[Question]] = defaultdict(list)
    for q in pool:
        by_chapter[q.chapter_id].append(q)
    for qs in by_chapter.values():
        rng.shuffle(qs)
    weight = {cid: qs[0].chapter.est_hours for cid, qs in by_chapter.items()}
    taken: dict[int, int] = defaultdict(int)
    picked: list[Question] = []
    while len(picked) < n and by_chapter:
        # Chapters that have already given many questions become less likely, so the paper spreads out.
        cids = list(by_chapter)
        cid = rng.choices(cids, weights=[weight[c] / (1 + 1.5 * taken[c]) for c in cids])[0]
        picked.append(by_chapter[cid].pop())
        taken[cid] += 1
        if not by_chapter[cid]:
            del by_chapter[cid]
    rng.shuffle(picked)
    return picked


def chapter_accuracy(db: Session, user_id: int) -> dict[int, dict]:
    """Per-chapter results across all submitted attempts."""
    rows = db.execute(
        select(Question.chapter_id, ExamAttemptItem.selected_index, ExamAttemptItem.correct_index,
               ExamAttemptItem.time_spent_seconds)
        .join(ExamAttemptItem, ExamAttemptItem.question_id == Question.id).join(ExamAttempt)
        .where(ExamAttempt.user_id == user_id, ExamAttempt.status == "submitted")).all()
    stats: dict[int, dict] = defaultdict(lambda: {"seen": 0, "attempted": 0, "correct": 0, "seconds": 0})
    for chapter_id, sel, cor, secs in rows:
        s = stats[chapter_id]
        s["seen"] += 1
        s["seconds"] += secs or 0
        if sel is not None:
            s["attempted"] += 1
            s["correct"] += int(sel == cor)
    for s in stats.values():
        s["accuracy"] = round(100 * s["correct"] / s["attempted"]) if s["attempted"] else None
    return stats


def readiness(db: Session, user: User, top_up: bool = True) -> dict:
    """How many never-seen questions this student has per section, and whether more are being written.
    Starts a background top-up when the pool is below the buffer."""
    from app.services import question_gen
    counts = question_gen.unseen_counts(db, user.id)
    unseen = {s: counts.get(s, 0) for s in SECTIONS}
    buffer = get_settings().unseen_buffer_per_section
    low = {s: buffer - n for s, n in unseen.items() if n < buffer}
    if low and top_up:
        question_gen.start_top_up(low)
    return {"unseen": unseen, "full_mocks_available": min(unseen.values()) // 45,
            "generating": question_gen.is_generating(), "can_generate": question_gen.enabled()}


def _not_ready(needed: dict[str, int], chapter_ids: list[int] | None = None) -> PaperNotReady:
    from app.services import question_gen
    buffer = get_settings().unseen_buffer_per_section
    if chapter_ids:
        started = question_gen.start_top_up_chapters(chapter_ids, sum(needed.values()) + 10)
    else:
        started = question_gen.start_top_up({s: n + buffer for s, n in needed.items()})
    return PaperNotReady(needed, generating=started or question_gen.is_generating())


def create_attempt(db: Session, user: User, mode: str, *, subject: str | None = None,
                   chapter_ids: list[int] | None = None, count: int | None = None,
                   strict_omr: bool = False, seed: int | None = None) -> ExamAttempt:
    if mode not in MODES:
        raise ExamError(f"Unknown test type '{mode}'.")
    open_attempt = db.scalar(select(ExamAttempt).where(ExamAttempt.user_id == user.id,
                                                       ExamAttempt.status == "in_progress"))
    if open_attempt is not None:
        expire_if_due(db, open_attempt)
        if open_attempt.status == "in_progress":
            raise ExamError(f"Finish or submit your current test first (test #{open_attempt.id}).")
    # A prepared paper that was never opened holds no answers; a new choice replaces it.
    db.execute(delete(ExamAttempt).where(ExamAttempt.user_id == user.id, ExamAttempt.status == "ready"))
    db.flush()

    rng = random.Random(seed)
    picked: list[Question] = []
    config: dict = {"mode": mode}

    if mode in ("full", "mini"):
        per = 45 if mode == "full" else min(max(count or 10, 5), 45)
        short = {}
        for s in SECTIONS:
            pool = _unseen(db, user.id, Question.subject == s)
            if len(pool) < per:
                short[s] = per - len(pool)
            picked += _blueprint_pick(pool, per, rng)
        if short:
            raise _not_ready(short)
        config["per_section"] = per
        title = "Full NEET mock (180 questions)" if mode == "full" else f"Mini NEET mock ({per * 4} questions)"
    elif mode == "subject":
        subjects = ["Botany", "Zoology"] if subject == "Biology" else [subject]
        if not subject or any(s not in SECTIONS for s in subjects):
            raise ExamError("Choose Physics, Chemistry, Botany, Zoology or Biology.")
        n = min(max(count or 45, 5), 90)
        short = {}
        for s in subjects:
            want = n // len(subjects)
            pool = _unseen(db, user.id, Question.subject == s)
            if len(pool) < want:
                short[s] = want - len(pool)
            picked += _blueprint_pick(pool, want, rng)
        if short:
            raise _not_ready(short)
        config["subject"] = subject
        title = f"{subject} practice"
    elif mode == "chapter":
        if not chapter_ids or len(chapter_ids) > 10:
            raise ExamError("Choose between 1 and 10 chapters.")
        n = min(max(count or 20, 5), 90)
        pool = _unseen(db, user.id, Question.chapter_id.in_(chapter_ids))
        if len(pool) < n:
            subj = db.scalar(select(SyllabusChapter.subject).where(SyllabusChapter.id == chapter_ids[0])) or "questions"
            raise _not_ready({subj: n - len(pool)}, chapter_ids)
        picked = _blueprint_pick(pool, n, rng)
        names = list(db.scalars(select(SyllabusChapter.name).where(SyllabusChapter.id.in_(chapter_ids))))
        config["chapter_ids"] = chapter_ids
        title = "Chapter test: " + ", ".join(names[:3]) + (f" +{len(names) - 3} more" if len(names) > 3 else "")
    else:  # weak
        acc = chapter_accuracy(db, user.id)
        weak = [cid for cid, s in acc.items() if s["attempted"] >= 2 and (s["accuracy"] or 0) < 60]
        if not weak:
            raise ExamError("No weak chapters yet. Weak chapters are ones where you got under 60% right in "
                            "at least 2 questions; take a few tests first.")
        n = min(max(count or 30, 5), 90)
        pool = _unseen(db, user.id, Question.chapter_id.in_(weak))
        if len(pool) < n:
            raise _not_ready({"weak-chapter": n - len(pool)}, weak)
        picked = _blueprint_pick(pool, n, rng)
        config["chapter_ids"] = weak
        title = "Weak-chapter practice"

    order = {s: i for i, s in enumerate(SECTIONS)}
    picked.sort(key=lambda q: order.get(q.subject, 9))  # NEET section order; mixed chapters within a section
    seconds = 60 * len(picked)  # NEET allows 180 minutes for 180 questions
    now = _now()
    attempt = ExamAttempt(user_id=user.id, mode=mode, title=title, config=config, pattern=NEET_PATTERN,
                          strict_omr=strict_omr, duration_seconds=seconds, started_at=now,
                          deadline_at=now + timedelta(seconds=seconds), max_score=4 * len(picked),
                          status="ready", booklet_code=rng.choice(BOOKLET_CODES))
    attempt.items = [ExamAttemptItem(question_id=q.id, position=i + 1, section=q.subject, correct_index=q.correct_index)
                     for i, q in enumerate(picked)]
    db.add(attempt)
    db.flush()
    attempt.roll_number = f"{(2700000000 + user.id * 1000 + attempt.id % 1000):010d}"[-10:]
    db.commit()
    return attempt


def start_attempt(db: Session, attempt: ExamAttempt) -> ExamAttempt:
    """Open the booklet: the clock starts now."""
    if attempt.status != "ready":
        return attempt
    now = _now()
    attempt.status, attempt.started_at = "in_progress", now
    attempt.deadline_at = now + timedelta(seconds=attempt.duration_seconds)
    db.commit()
    return attempt


def remaining_seconds(attempt: ExamAttempt) -> int:
    if attempt.status == "ready":
        return attempt.duration_seconds
    return max(0, int((_aware(attempt.deadline_at) - _now()).total_seconds()))


def expire_if_due(db: Session, attempt: ExamAttempt) -> bool:
    if attempt.status == "in_progress" and _now() > _aware(attempt.deadline_at) + timedelta(seconds=GRACE_SECONDS):
        submit(db, attempt, auto=True)
        return True
    return False


def save_answer(db: Session, attempt: ExamAttempt, position: int, *, selected_index: int | None,
                marked_for_review: bool, time_spent_delta: int) -> ExamAttemptItem:
    if expire_if_due(db, attempt):
        raise ExamError("Time is up. Your test was submitted automatically.")
    if attempt.status == "ready":
        raise ExamError("Open the test booklet first.")
    if attempt.status != "in_progress":
        raise ExamError("This test has already been submitted.")
    item = next((i for i in attempt.items if i.position == position), None)
    if item is None:
        raise ExamError("No such question number.")
    if selected_index is not None and not 0 <= selected_index <= 3:
        raise ExamError("Choose option 1, 2, 3 or 4.")
    if attempt.strict_omr and item.selected_index is not None and selected_index != item.selected_index:
        raise ExamError("Strict OMR mode: a filled bubble cannot be changed, just like the real answer sheet.")
    item.selected_index = selected_index
    item.marked_for_review = marked_for_review
    item.visited = True
    item.time_spent_seconds += max(0, min(time_spent_delta, 600))
    db.commit()
    return item


def submit(db: Session, attempt: ExamAttempt, auto: bool = False) -> ExamAttempt:
    if attempt.status == "submitted":
        return attempt
    if attempt.status == "ready":
        raise ExamError("This test has not been started.")
    score = 0
    for i in attempt.items:
        if i.selected_index is not None:
            score += 4 if i.selected_index == i.correct_index else -1
    attempt.score, attempt.status = score, "submitted"
    attempt.submitted_at = min(_now(), _aware(attempt.deadline_at))
    attempt.auto_submitted = auto

    if attempt.mode == "full":  # only full-length mocks feed the 720-mark trend on the Mock Tests page
        sections = _section_stats(attempt)
        weak = _weak_chapters_by_subject(attempt)
        bio = [sections["Botany"], sections["Zoology"]]
        mt = MockTest(user_id=attempt.user_id, name=attempt.title, provider="NEET Compass practice test",
                      test_date=date.today(), total_score=score, max_score=attempt.max_score,
                      notes=f"Recorded automatically from practice test #{attempt.id}.")
        mt.subjects = [
            MockTestSubjectScore(subject="Physics", score=sections["Physics"]["score"], max_score=sections["Physics"]["max"],
                                 weak_topics=weak.get("Physics", [])),
            MockTestSubjectScore(subject="Chemistry", score=sections["Chemistry"]["score"],
                                 max_score=sections["Chemistry"]["max"], weak_topics=weak.get("Chemistry", [])),
            MockTestSubjectScore(subject="Biology", score=sum(b["score"] for b in bio), max_score=sum(b["max"] for b in bio),
                                 weak_topics=weak.get("Botany", []) + weak.get("Zoology", [])),
        ]
        db.add(mt)
        db.flush()
        attempt.mock_test_id = mt.id
    db.commit()
    return attempt


def report_question(db: Session, attempt: ExamAttempt, position: int, user: User, reason: str, note: str | None) -> dict:
    if attempt.status != "submitted":
        raise ExamError("You can report a question after submitting the test.")
    if reason not in REPORT_REASONS:
        raise ExamError("Choose a reason.")
    item = next((i for i in attempt.items if i.position == position), None)
    if item is None:
        raise ExamError("No such question number.")
    q = item.question
    if db.scalar(select(QuestionReport.id).where(QuestionReport.question_id == q.id, QuestionReport.user_id == user.id)):
        return {"ok": True, "already_reported": True}
    db.add(QuestionReport(question_id=q.id, user_id=user.id, reason=reason, note=(note or "")[:1000] or None))
    q.report_count += 1
    # Unreviewed questions are hidden after a couple of reports until an admin looks at them.
    if q.report_count >= HIDE_AFTER_REPORTS and q.review_status in ("sample", "ai_checked"):
        q.review_status = "flagged"
    db.commit()
    return {"ok": True, "already_reported": False}


def _section_stats(attempt: ExamAttempt) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in attempt.items:
        s = out.setdefault(i.section, {"section": i.section, "questions": 0, "attempted": 0, "correct": 0,
                                       "wrong": 0, "score": 0, "max": 0, "seconds": 0})
        s["questions"] += 1
        s["max"] += 4
        s["seconds"] += i.time_spent_seconds
        if i.selected_index is not None:
            s["attempted"] += 1
            if i.selected_index == i.correct_index:
                s["correct"] += 1
                s["score"] += 4
            else:
                s["wrong"] += 1
                s["score"] -= 1
    for s in out.values():
        s["accuracy"] = round(100 * s["correct"] / s["attempted"]) if s["attempted"] else None
        s["avg_seconds"] = round(s["seconds"] / s["questions"]) if s["questions"] else 0
    return out


def _chapter_stats(attempt: ExamAttempt) -> list[dict]:
    by: dict[int, dict] = {}
    for i in attempt.items:
        ch = i.question.chapter
        s = by.setdefault(ch.id, {"chapter_id": ch.id, "chapter": ch.name, "subject": ch.subject, "questions": 0,
                                  "attempted": 0, "correct": 0})
        s["questions"] += 1
        if i.selected_index is not None:
            s["attempted"] += 1
            s["correct"] += int(i.selected_index == i.correct_index)
    for s in by.values():
        s["accuracy"] = round(100 * s["correct"] / s["attempted"]) if s["attempted"] else None
    # Weakest answered chapters first; chapters with no answers last.
    return sorted(by.values(), key=lambda s: (s["accuracy"] is None, s["accuracy"] or 0, s["chapter"]))


def _weak_chapters_by_subject(attempt: ExamAttempt) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for c in _chapter_stats(attempt):
        if c["attempted"] and c["accuracy"] < 50:
            out[c["subject"]].append(c["chapter"])
    return out


def _question_view(i: ExamAttemptItem, reveal: bool) -> dict:
    q = i.question
    d = {"position": i.position, "section": i.section, "stem": q.stem, "options": q.options, "format": q.qformat,
         "selected_index": i.selected_index, "marked_for_review": i.marked_for_review,
         "visited": i.visited, "review_status": q.review_status}
    if reveal:  # like the printed booklet, chapter names only appear in the answer review
        d.update(correct_index=i.correct_index, explanation=q.explanation, topic=q.topic, difficulty=q.difficulty,
                 chapter=q.chapter.name, time_spent_seconds=i.time_spent_seconds,
                 outcome="skipped" if i.selected_index is None else
                 ("correct" if i.selected_index == i.correct_index else "wrong"))
    return d


def attempt_view(db: Session, attempt: ExamAttempt) -> dict:
    expire_if_due(db, attempt)
    done = attempt.status == "submitted"
    statuses = {i.question.review_status for i in attempt.items}
    base = {"id": attempt.id, "title": attempt.title, "mode": attempt.mode, "status": attempt.status,
            "strict_omr": attempt.strict_omr, "pattern": attempt.pattern, "duration_seconds": attempt.duration_seconds,
            "started_at": attempt.started_at, "submitted_at": attempt.submitted_at,
            "booklet_code": attempt.booklet_code, "roll_number": attempt.roll_number,
            "remaining_seconds": 0 if done else remaining_seconds(attempt),
            "has_sample_questions": "sample" in statuses, "has_ai_questions": "ai_checked" in statuses,
            "section_counts": {s: sum(1 for i in attempt.items if i.section == s) for s in SECTIONS
                               if any(i.section == s for i in attempt.items)},
            # The booklet stays sealed until the student opens it and the clock starts.
            "questions": [] if attempt.status == "ready" else [_question_view(i, reveal=done) for i in attempt.items]}
    if not done:
        return base
    sections = _section_stats(attempt)
    attempted = sum(s["attempted"] for s in sections.values())
    wrong = sum(s["wrong"] for s in sections.values())
    base["result"] = {
        "score": attempt.score, "max_score": attempt.max_score, "auto_submitted": attempt.auto_submitted,
        "attempted": attempted, "correct": attempted - wrong, "wrong": wrong,
        "skipped": len(attempt.items) - attempted, "negative_marks": wrong,
        "accuracy": round(100 * (attempted - wrong) / attempted) if attempted else None,
        "time_used_seconds": int((_aware(attempt.submitted_at) - _aware(attempt.started_at)).total_seconds()),
        "focus_lost_count": attempt.focus_lost_count,
        "sections": [sections[s] for s in SECTIONS if s in sections],
        "chapters": _chapter_stats(attempt),
        "recorded_as_mock_test": attempt.mock_test_id is not None,
        "advice": _advice(sections, attempted, wrong, len(attempt.items)),
    }
    return base


def _advice(sections: dict, attempted: int, wrong: int, total: int) -> list[str]:
    tips = []
    if attempted and wrong / attempted > 0.3:
        tips.append(f"{wrong} wrong answers cost you {wrong} marks through negative marking. Attempt a question only "
                    "when you can eliminate at least two options.")
    if total and (total - attempted) / total > 0.25:
        tips.append("You left more than a quarter of the questions blank. Practise speed with timed chapter tests.")
    slow = [s["section"] for s in sections.values() if s["avg_seconds"] > 75]
    if slow:
        tips.append("You averaged over 75 seconds a question in " + ", ".join(slow) +
                    ". The exam allows about 60 seconds a question overall.")
    weakest = min((s for s in sections.values() if s["accuracy"] is not None), key=lambda s: s["accuracy"], default=None)
    if weakest and weakest["accuracy"] < 60:
        tips.append(f"{weakest['section']} had the lowest accuracy ({weakest['accuracy']}%). Review the chapters "
                    "listed below before your next test.")
    return tips


def attempt_summary(a: ExamAttempt) -> dict:
    return {"id": a.id, "title": a.title, "mode": a.mode, "status": a.status, "score": a.score,
            "max_score": a.max_score, "questions": len(a.items), "started_at": a.started_at,
            "submitted_at": a.submitted_at, "booklet_code": a.booklet_code,
            "remaining_seconds": remaining_seconds(a) if a.status != "submitted" else 0}
