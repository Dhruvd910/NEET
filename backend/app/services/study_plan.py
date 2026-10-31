"""Week-by-week NEET study plan, shaped by the student's class.

- Class 11: Class 11 chapters first (alongside school), then Class 12, then full revision and mocks.
- Class 12: Class 12 chapters first while revising Class 11; board-exam weeks (mid-Feb to March)
  drop to light NEET revision; then full revision and mocks.
- Dropper / repeater: the whole syllabus, starting with the chapters furthest behind, then mocks.

Chapter hours are rough planning estimates. Chapters the student has marked as learnt or mastered
need less time, and chapters with low accuracy in practice tests get extra practice. The NEET date is
an estimate (first Sunday of May) unless the student enters the official date.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChapterProgress, StudyPlan, StudyTask, SyllabusChapter, User
from app.services.exams import chapter_accuracy

CLASSES = {"11", "12", "dropper"}
SUBJECT_ORDER = ["Physics", "Chemistry", "Botany", "Zoology"]
STATUS_RANK = {"not_started": 0, "learning": 1, "revised": 2, "mastered": 3}
MOCK_HOURS = 5.0  # 3-hour paper + 2 hours of analysis


class PlanError(ValueError):
    pass


def estimated_exam_date(year: int) -> date:
    """First Sunday of May: NEET-UG has usually been held in early May. Always an estimate."""
    d = date(year, 5, 1)
    return d + timedelta(days=(6 - d.weekday()) % 7)


def default_exam_year(current_class: str, today: date) -> int:
    if current_class == "11":  # academic year runs roughly April–March
        return today.year + 2 if today.month >= 4 else today.year + 1
    if current_class == "12":
        return today.year + 1 if today.month >= 6 else today.year
    return today.year if today < estimated_exam_date(today.year) - timedelta(days=21) else today.year + 1


def _assumed_status(current_class: str, ch: SyllabusChapter) -> str:
    if current_class == "11":
        return "not_started"
    if current_class == "12":
        return "learning" if ch.class_level == "11" else "not_started"
    return "learning"


@dataclass
class _Chapter:
    ch: SyllabusChapter
    status: str
    weak: bool
    learn_left: float
    revisions: int = 0
    last_week: int = -99
    revise_hours: float = field(init=False)

    def __post_init__(self):
        self.revise_hours = round(max(2.0, self.ch.est_hours * (0.25 if self.status != "mastered" else 0.1)), 1)


def _interleave(chapters: list[_Chapter]) -> deque:
    """Alternate subjects so a week mixes Physics, Chemistry and Biology."""
    by_subject = {s: deque(c for c in chapters if c.ch.subject == s) for s in SUBJECT_ORDER}
    out = deque()
    while any(by_subject.values()):
        for s in SUBJECT_ORDER:
            if by_subject[s]:
                out.append(by_subject[s].popleft())
    return out


def build_plan(db: Session, user: User, *, current_class: str, start: date, exam_date: date,
               exam_date_is_estimate: bool, weekday_hours: float, weekend_hours: float) -> StudyPlan:
    if current_class not in CLASSES:
        raise PlanError("Class must be 11, 12 or dropper.")
    if not (0 <= weekday_hours <= 12 and 0 <= weekend_hours <= 14) or weekday_hours + weekend_hours <= 0:
        raise PlanError("Enter realistic study hours per day (weekday up to 12, weekend up to 14).")
    monday = start - timedelta(days=start.weekday())
    weeks = [monday + timedelta(weeks=i) for i in range((exam_date - monday).days // 7)]
    if len(weeks) < 2:
        raise PlanError("The exam date is less than two weeks away. Focus on revision and full mocks.")

    progress = {p.chapter_id: p.status for p in db.scalars(select(ChapterProgress).where(ChapterProgress.user_id == user.id))}
    acc = chapter_accuracy(db, user.id)
    weak_ids = {cid for cid, s in acc.items() if s["attempted"] >= 2 and (s["accuracy"] or 0) < 50}
    chapters = []
    for ch in db.scalars(select(SyllabusChapter).order_by(SyllabusChapter.sort_order)):
        status = progress.get(ch.id) or _assumed_status(current_class, ch)
        chapters.append(_Chapter(ch=ch, status=status, weak=ch.id in weak_ids,
                                 learn_left=float(ch.est_hours) if status == "not_started" else 0.0))

    weekly = 5 * weekday_hours + 2 * weekend_hours
    n = len(weeks)
    final_weeks = min(max(3, round(0.2 * n)), 12, n - 1)
    learn_weeks = n - final_weeks

    to_learn = [c for c in chapters if c.learn_left > 0]
    if current_class == "11":
        to_learn.sort(key=lambda c: (c.ch.class_level, c.ch.sort_order))
        queue = _interleave([c for c in to_learn if c.ch.class_level == "11"])
        queue.extend(_interleave([c for c in to_learn if c.ch.class_level == "12"]))
    else:  # class 12 / dropper: Class 12 chapters first, then the rest
        queue = _interleave([c for c in to_learn if c.ch.class_level == "12"])
        queue.extend(_interleave([c for c in to_learn if c.ch.class_level == "11"]))

    plan = StudyPlan(user_id=user.id, current_class=current_class, start_date=start, exam_date=exam_date,
                     exam_date_is_estimate=exam_date_is_estimate, weekday_hours=weekday_hours, weekend_hours=weekend_hours)
    tasks: list[StudyTask] = []
    learned_in: dict[int, int] = {}
    total_learn_needed = sum(c.learn_left for c in chapters)

    def add(w: int, phase: str, kind: str, title: str, hours: float, detail: str | None = None,
            chapter: SyllabusChapter | None = None):
        tasks.append(StudyTask(week_index=w, week_start=weeks[w], phase=phase, kind=kind, title=title,
                               detail=detail, est_hours=round(hours, 1), chapter_id=chapter.id if chapter else None))

    def revise(w: int, phase: str, budget: float) -> None:
        """Spend budget on revision: weak and least-revised chapters first, never the same chapter twice in 3 weeks."""
        pool = [c for c in chapters if c.learn_left == 0 and w - learned_in.get(c.ch.id, -99) >= 1
                and w - c.last_week >= 3]
        pool.sort(key=lambda c: (not c.weak, c.revisions, STATUS_RANK[c.status], c.ch.sort_order))
        for c in pool:
            if budget < 1:
                break
            hours = min(c.revise_hours, budget)
            add(w, phase, "revise", f"Revise: {c.ch.name}", hours,
                ("Weak in your tests — redo NCERT examples and wrong questions. " if c.weak else "")
                + "Read NCERT, make short notes, then take a 15–20 question chapter test.", c.ch)
            c.revisions += 1
            c.last_week = w
            budget -= hours

    class12_starts = date(exam_date.year - 1, 4, 1)

    def is_board(w: int) -> bool:
        wk = weeks[w]
        return current_class == "12" and wk.year == exam_date.year and (
            (wk.month == 2 and wk.day >= 15) or wk.month == 3)

    learn_done_week = None
    for w in range(n):
        capacity = weekly
        if is_board(w):
            capacity = round(weekly * 0.3, 1)
            add(w, "Board exams", "board", "Board exams: keep NEET to light revision",
                0, "Approximate window — follow your board's date sheet. Revise formulas and NCERT diagrams only.")
            revise(w, "Board exams", capacity)
            continue

        if w < learn_weeks:
            # Class 11 students start Class 12 chapters with the Class 12 school year (April).
            waiting = (current_class == "11" and queue and queue[0].ch.class_level == "12"
                       and weeks[w] < class12_starts)
            phase = ("Learn Class 11" if current_class == "11" and queue and queue[0].ch.class_level == "11" else
                     "Revise Class 11 and practise" if waiting else
                     "Learn the syllabus" if queue else "Revise and practise")
            # Full mocks once most of the syllabus is done; chapter tests before that.
            learned_share = 1 - (sum(c.learn_left for c in chapters) / total_learn_needed) if total_learn_needed else 1
            if learned_share >= 0.6 and w % 3 == 0 and capacity >= 12:
                add(w, phase, "mock", "Full NEET mock (3 hours) + analysis", MOCK_HOURS,
                    "Sit it in one go at 2 pm like the real exam. Spend the analysis time on every wrong and skipped question.")
                capacity -= MOCK_HOURS
            recent = [cid for cid, lw in learned_in.items() if w - lw in (1, 2)]
            if recent:
                hours = min(2.0, capacity * 0.15)
                add(w, phase, "practice", "Chapter tests on last weeks' chapters", hours,
                    "Timed, 1 minute per question. Note every mistake in an error log.")
                capacity -= hours
            # Normally 70% of the week goes to new chapters; up to 90% when behind schedule.
            backlog = sum(c.learn_left for c in queue)
            weeks_left = sum(1 for x in range(w, learn_weeks) if not is_board(x)) or 1
            share = 0.7 if backlog <= 0.7 * capacity * weeks_left else 0.9
            budget = capacity * share if queue and not waiting else 0.0
            while queue and budget >= 1:
                c = queue[0]
                hours = min(c.learn_left, budget)
                part = " (continued)" if c.learn_left < c.ch.est_hours else " (part 1)" if hours < c.learn_left else ""
                add(w, phase, "learn", f"Learn: {c.ch.name}{part}", hours,
                    f"{c.ch.subject}, Class {c.ch.class_level}. NCERT first, then solved examples and 30+ practice questions.",
                    c.ch)
                c.learn_left -= hours
                budget -= hours
                capacity -= hours
                if c.learn_left <= 0.01:
                    c.learn_left = 0
                    learned_in[c.ch.id] = w
                    queue.popleft()
            if not queue and learn_done_week is None:
                learn_done_week = w
            revise(w, phase, capacity)
        else:
            phase = "Final revision and mocks"
            last_month = n - w <= 4
            mocks = 2 if last_month and capacity >= 2 * MOCK_HOURS + 4 else 1
            for k in range(mocks):
                add(w, phase, "mock", f"Full NEET mock{' ' + str(k + 1) if mocks > 1 else ''} (3 hours) + analysis",
                    MOCK_HOURS, "Same time of day as the exam. Use the OMR sheet in strict mode.")
            capacity -= mocks * MOCK_HOURS
            weak = [c for c in chapters if c.weak]
            if weak and capacity >= 2:
                add(w, phase, "practice", "Weak-chapter practice test", 2,
                    "Use 'Practise my weak chapters' on the Practice page.")
                capacity -= 2
            revise(w, phase, capacity)

    unfinished = [c.ch.name for c in queue]
    plan.summary = {
        "weeks": n, "weekly_hours": weekly, "final_phase_weeks": final_weeks,
        "first_time_study_hours_needed": round(total_learn_needed),
        "first_time_study_hours_available": round(sum(t.est_hours for t in tasks if t.kind == "learn")),
        "syllabus_finished_by": weeks[learn_done_week].isoformat() if learn_done_week is not None else None,
        "unfinished_chapters": unfinished,
        "weak_chapters": sorted(c.ch.name for c in chapters if c.weak),
        "assumptions": [
            "Chapter hours are rough planning estimates; adjust your pace if a chapter takes longer.",
            "Chapters you have not marked on the syllabus page are assumed "
            + {"11": "not started.", "12": "not started for Class 12, and studied once (needs revision) for Class 11.",
               "dropper": "studied once (needs revision)."}[current_class],
            "The exam date is an estimate (first Sunday of May). Enter the official date once NTA announces it."
            if exam_date_is_estimate else "Exam date entered by you.",
        ],
    }
    if unfinished:
        plan.summary["warning"] = (f"{len(unfinished)} chapter(s) do not fit before the final revision phase. "
                                   "Increase your daily hours, or mark chapters you already know on the syllabus page.")
    plan.tasks = tasks
    for old in db.scalars(select(StudyPlan).where(StudyPlan.user_id == user.id)):
        db.delete(old)
    db.add(plan)
    db.commit()
    return plan


def plan_view(plan: StudyPlan, today: date | None = None) -> dict:
    today = today or date.today()
    weeks: dict[int, dict] = {}
    for t in plan.tasks:
        w = weeks.setdefault(t.week_index, {"week_index": t.week_index, "week_start": t.week_start, "phase": t.phase,
                                            "hours": 0.0, "tasks": []})
        w["hours"] = round(w["hours"] + t.est_hours, 1)
        w["tasks"].append({"id": t.id, "kind": t.kind, "title": t.title, "detail": t.detail, "est_hours": t.est_hours,
                           "chapter_id": t.chapter_id, "status": t.status})
    ordered = [weeks[k] for k in sorted(weeks)]
    current = next((w["week_index"] for w in ordered if w["week_start"] <= today < w["week_start"] + timedelta(days=7)),
                   ordered[0]["week_index"] if ordered else None)
    done = sum(1 for t in plan.tasks if t.status == "done")
    return {"id": plan.id, "current_class": plan.current_class, "start_date": plan.start_date, "exam_date": plan.exam_date,
            "exam_date_is_estimate": plan.exam_date_is_estimate, "weekday_hours": plan.weekday_hours,
            "weekend_hours": plan.weekend_hours, "summary": plan.summary, "current_week": current,
            "progress": {"done": done, "total": len(plan.tasks)}, "weeks": ordered}
