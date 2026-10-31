"""Practice tests (NEET format), syllabus progress, class-based study plans and nearby facilities."""
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.models import College, ExamAttempt, MockTest, Question, SyllabusChapter
from app.practice_seed import _hash
from app.services import study_plan
from tests.conftest import PASSWORD


def fresh_student(client):
    email = f"p-{uuid.uuid4().hex[:8]}@example.test"
    r = client.post("/api/auth/register", json={"email": email, "password": PASSWORD, "is_minor": False,
                                               "accept_privacy_notice": True})
    assert r.status_code == 201
    return client


def test_pattern_and_bank(client):
    body = client.get("/api/exams/pattern").json()
    p = body["pattern"]
    assert p["total_questions"] == 180 and p["duration_minutes"] == 180
    assert (p["marks_correct"], p["marks_wrong"]) == (4, -1)
    assert [s["name"] for s in p["sections"]] == ["Physics", "Chemistry", "Botany", "Zoology"]
    assert all(body["bank"][s]["sample"] >= 20 for s in ("Physics", "Chemistry", "Botany", "Zoology"))


def paper(client, **body) -> int:
    """Prepare a paper and open the booklet (starts the clock)."""
    r = client.post("/api/exams/attempts", json=body)
    assert r.status_code == 201, r.text
    assert client.post(f"/api/exams/attempts/{r.json()['id']}/start").status_code == 200
    return r.json()["id"]


def test_mini_mock_full_cycle(client, db):
    fresh_student(client)
    r = client.post("/api/exams/attempts", json={"mode": "mini", "count": 5, "strict_omr": True})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert r.json()["questions"] == 20 and r.json()["status"] == "ready" and r.json()["booklet_code"]

    sealed = client.get(f"/api/exams/attempts/{aid}").json()
    assert sealed["status"] == "ready" and sealed["questions"] == [] and sealed["roll_number"]  # booklet still sealed
    assert sealed["section_counts"] == {"Physics": 5, "Chemistry": 5, "Botany": 5, "Zoology": 5}
    assert client.put(f"/api/exams/attempts/{aid}/answers/1", json={"selected_index": 0}).status_code == 409
    opened = client.post(f"/api/exams/attempts/{aid}/start").json()
    assert opened["status"] == "in_progress" and opened["remaining_seconds"] > 19 * 60
    assert client.post("/api/exams/attempts", json={"mode": "mini"}).status_code == 409  # one test at a time

    view = client.get(f"/api/exams/attempts/{aid}").json()
    assert view["status"] == "in_progress" and view["has_sample_questions"]
    assert all("chapter" not in q for q in view["questions"])  # like the printed booklet
    assert [q["section"] for q in view["questions"][:5]] == ["Physics"] * 5
    assert view["questions"][-1]["section"] == "Zoology"
    assert all("correct_index" not in q and "explanation" not in q for q in view["questions"])  # no answer leaks

    attempt = db.get(ExamAttempt, aid)
    key = {i.position: i.correct_index for i in attempt.items}
    # 3 right, 2 wrong, rest skipped
    for pos in (1, 2, 3):
        assert client.put(f"/api/exams/attempts/{aid}/answers/{pos}",
                          json={"selected_index": key[pos], "time_spent_delta": 40}).status_code == 200
    for pos in (4, 5):
        client.put(f"/api/exams/attempts/{aid}/answers/{pos}", json={"selected_index": (key[pos] + 1) % 4})
    changed = client.put(f"/api/exams/attempts/{aid}/answers/1", json={"selected_index": (key[1] + 1) % 4})
    assert changed.status_code == 409 and "Strict OMR" in changed.json()["detail"]
    assert client.put(f"/api/exams/attempts/{aid}/answers/6", json={"selected_index": None,
                                                                    "marked_for_review": True}).status_code == 200
    client.post(f"/api/exams/attempts/{aid}/focus-lost")

    res = client.post(f"/api/exams/attempts/{aid}/submit").json()
    r = res["result"]
    assert (r["score"], r["correct"], r["wrong"], r["skipped"], r["max_score"]) == (10, 3, 2, 15, 80)
    assert r["sections"][0]["section"] == "Physics" and r["sections"][0]["score"] == 10
    assert r["focus_lost_count"] == 1 and not r["recorded_as_mock_test"]
    assert all("correct_index" in q and q["outcome"] in ("correct", "wrong", "skipped") for q in res["questions"])
    assert client.put(f"/api/exams/attempts/{aid}/answers/7", json={"selected_index": 0}).status_code == 409

    perf = client.get("/api/exams/performance").json()["chapters"]
    assert perf and all("accuracy" in c for c in perf)


def test_time_limit_is_enforced_by_the_server(client, db):
    fresh_student(client)
    aid = paper(client, mode="subject", subject="Physics", count=5)
    a = db.get(ExamAttempt, aid)
    a.deadline_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()
    r = client.put(f"/api/exams/attempts/{aid}/answers/1", json={"selected_index": 0})
    assert r.status_code == 409 and "Time is up" in r.json()["detail"]
    view = client.get(f"/api/exams/attempts/{aid}").json()
    assert view["status"] == "submitted" and view["result"]["auto_submitted"]


def test_chapter_and_biology_practice(client, db):
    fresh_student(client)
    ch = db.scalar(select(SyllabusChapter).where(SyllabusChapter.code == "CHE-11-06"))
    r = client.post("/api/exams/attempts", json={"mode": "chapter", "chapter_ids": [ch.id], "count": 5})
    assert r.status_code == 422  # only 2 questions in that chapter (and generation is off in tests)
    ids = list(db.scalars(select(SyllabusChapter.id).where(SyllabusChapter.subject == "Chemistry")))
    aid = paper(client, mode="chapter", chapter_ids=ids[:10], count=8)
    assert len(client.get(f"/api/exams/attempts/{aid}").json()["questions"]) == 8
    client.post(f"/api/exams/attempts/{aid}/submit")
    aid = paper(client, mode="subject", subject="Biology", count=10)
    view = client.get(f"/api/exams/attempts/{aid}").json()
    assert {q["section"] for q in view["questions"]} == {"Botany", "Zoology"}
    client.post(f"/api/exams/attempts/{aid}/submit")
    assert client.post("/api/exams/attempts", json={"mode": "weak"}).status_code == 422  # no history of mistakes yet


def test_full_mock_is_recorded_for_trends(client, db):
    # Top the bank up with synthetic, clearly-labelled questions so a 180-question paper can be built.
    for subject, prefix in (("Physics", "PHY"), ("Chemistry", "CHE"), ("Botany", "BOT"), ("Zoology", "ZOO")):
        ch = db.scalar(select(SyllabusChapter).where(SyllabusChapter.code == f"{prefix}-11-01"))
        have = len(db.scalars(select(Question.id).where(Question.subject == subject,
                                                        Question.review_status.in_(["sample", "reviewed"]))).all())
        for k in range(max(0, 45 - have)):
            stem = f"TEST FIXTURE {subject} question {k} {uuid.uuid4().hex[:6]}"
            opts = ["a", "b", "c", "d"]
            db.add(Question(subject=subject, chapter_id=ch.id, stem=stem, options=opts, correct_index=0,
                            review_status="reviewed", content_hash=_hash(stem, opts), source_name="TEST FIXTURE"))
    db.commit()
    fresh_student(client)
    r = client.post("/api/exams/attempts", json={"mode": "full"})
    assert r.status_code == 201 and r.json()["questions"] == 180 and r.json()["max_score"] == 720
    assert client.post(f"/api/exams/attempts/{r.json()['id']}/start").json()["remaining_seconds"] > 179 * 60
    res = client.post(f"/api/exams/attempts/{r.json()['id']}/submit").json()
    assert res["result"]["score"] == 0 and res["result"]["recorded_as_mock_test"]
    mt = db.get(MockTest, db.get(ExamAttempt, r.json()["id"]).mock_test_id)
    assert mt.max_score == 720 and {s.subject for s in mt.subjects} == {"Physics", "Chemistry", "Biology"}


def test_syllabus_progress(client, db):
    fresh_student(client)
    syl = client.get("/api/syllabus").json()
    assert len(syl["chapters"]) >= 80 and syl["source"]["verification_status"] == "pending_review"
    cid = syl["chapters"][0]["id"]
    assert client.put(f"/api/syllabus/progress/{cid}", json={"status": "mastered", "confidence": 5}).status_code == 200
    assert client.get("/api/syllabus/progress").json()[str(cid)]["status"] == "mastered"
    assert client.put(f"/api/syllabus/progress/{cid}", json={"status": "great"}).status_code == 422


def test_exam_date_defaults_follow_the_class():
    assert study_plan.estimated_exam_date(2027) == date(2027, 5, 2)  # first Sunday of May 2027
    assert study_plan.default_exam_year("11", date(2026, 10, 30)) == 2028
    assert study_plan.default_exam_year("11", date(2027, 2, 1)) == 2028
    assert study_plan.default_exam_year("12", date(2026, 10, 30)) == 2027
    assert study_plan.default_exam_year("dropper", date(2026, 10, 30)) == 2027


def _plan(client, **kw):
    r = client.post("/api/study-plan", json={"weekday_hours": 4, "weekend_hours": 8, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _tasks(plan):
    return [t for w in plan["weeks"] for t in w["tasks"]]


def test_class_11_plan_learns_class_11_first_and_ends_with_mocks(client, db):
    fresh_student(client)
    plan = _plan(client, current_class="11")
    assert plan["exam_date_is_estimate"] and plan["exam_date"].endswith("-05-02") or plan["exam_date"][5:7] == "05"
    learn = [t for t in _tasks(plan) if t["kind"] == "learn"]
    levels = [db.get(SyllabusChapter, t["chapter_id"]).class_level for t in learn]
    first_12 = levels.index("12")
    assert "11" not in levels[first_12:]  # every Class 11 chapter is learnt before Class 12 starts
    last = plan["weeks"][-1]
    assert last["phase"] == "Final revision and mocks" and any(t["kind"] == "mock" for t in last["tasks"])
    assert not plan["summary"]["unfinished_chapters"]
    for w in plan["weeks"]:
        assert w["hours"] <= 4 * 5 + 8 * 2 + 0.5


def test_class_12_plan_has_board_weeks_and_uses_progress(client, db):
    fresh_student(client)
    exam = date.today().replace(year=date.today().year + 1, month=5, day=2)
    plan = _plan(client, current_class="12", exam_date=exam.isoformat())
    assert not plan["exam_date_is_estimate"]
    board = [w for w in plan["weeks"] if w["phase"] == "Board exams"]
    assert board and all(w["hours"] <= (4 * 5 + 8 * 2) * 0.3 + 0.5 for w in board)
    learn = [t for t in _tasks(plan) if t["kind"] == "learn"]
    assert learn and all(db.get(SyllabusChapter, t["chapter_id"]).class_level == "12" for t in learn)

    # Finishing a chapter's learning moves it forward on the syllabus tracker.
    cid = learn[0]["chapter_id"]
    for t in [t for t in learn if t["chapter_id"] == cid]:
        assert client.patch(f"/api/study-plan/tasks/{t['id']}", json={"status": "done"}).status_code == 200
    assert client.get("/api/syllabus/progress").json()[str(cid)]["status"] == "learning"
    assert client.get("/api/study-plan").json()["progress"]["done"] >= 1


def test_too_few_hours_warns_about_unfinished_chapters(client):
    fresh_student(client)
    soon = date.today() + timedelta(weeks=8)
    plan = _plan(client, current_class="dropper", exam_date=soon.isoformat(), weekday_hours=0.5, weekend_hours=1)
    assert "warning" not in plan["summary"]  # dropper: syllabus assumed studied once → revision only
    fresh_student(client)
    plan = _plan(client, current_class="11", exam_date=soon.isoformat(), weekday_hours=0.5, weekend_hours=1)
    assert plan["summary"]["unfinished_chapters"] and "warning" in plan["summary"]
    assert client.post("/api/study-plan", json={"exam_date": soon.isoformat()}).status_code == 422  # no class known


def test_question_import(admin, db):
    csv_text = ("chapter_code,topic,difficulty,question,option_1,option_2,option_3,option_4,answer,explanation\n"
                f"PHY-12-03,Ohm's law,easy,Unique Q {uuid.uuid4().hex},1 A,2 A,3 A,4 A,2,V = IR\n"
                "PHY-99-99,x,easy,Bad chapter,a,b,c,d,1,\n"
                "PHY-12-03,x,easy,Same options,a,a,c,d,1,\n"
                "PHY-12-03,x,easy,Bad answer,a,b,c,d,5,\n")
    r = admin.post("/api/admin/questions/import", data={"data_source_code": "DEMO", "source_name": "Test bank"},
                   files={"file": ("q.csv", csv_text.encode(), "text/csv")})
    assert r.status_code == 200 and (r.json()["inserted"], r.json()["skipped"]) == (1, 3)
    q = db.scalar(select(Question).where(Question.source_name == "Test bank"))
    assert q.review_status == "draft" and q.correct_index == 1  # drafts are never served
    r = admin.post("/api/admin/questions/import", data={"data_source_code": "MH-CET", "source_name": "x" * 5},
                   files={"file": ("q.csv", csv_text.encode(), "text/csv")})
    assert r.status_code == 422  # source terms not reviewed


def test_nearby_places_are_grouped_and_demo_locations_hidden(client, db):
    demo = db.scalar(select(College).where(College.is_demo.is_(True)))
    d = client.get(f"/api/colleges/{demo.id}").json()
    assert d["overview"]["latitude"] is None
    cats = {n["category"] for n in d["nearby"]}
    assert {"Getting around", "Food", "Stay (outside campus)"} <= cats
    assert all(n["latitude"] is None for n in d["nearby"])
    near = [n for n in d["nearby"] if n["distance_km"] is not None and n["distance_km"] <= 3]
    assert all(n["walk_minutes"] for n in near)


def test_questions_never_repeat_for_a_student(client, db):
    fresh_student(client)
    seen: set[int] = set()
    while min(client.get("/api/exams/readiness").json()["unseen"].values()) >= 20:  # until the bank is used up
        aid = paper(client, mode="mini", count=20)
        ids = {i.question_id for i in db.get(ExamAttempt, aid).items}
        assert not ids & seen, "a question was repeated"
        seen |= ids
        client.post(f"/api/exams/attempts/{aid}/submit")
    assert len(seen) >= 80
    r = client.post("/api/exams/attempts", json={"mode": "mini", "count": 20})
    # Every question has been seen and generation is off in tests: refuse rather than repeat.
    assert r.status_code == 422 and r.json()["status"] == "preparing" and "already seen" in r.json()["detail"]
    ready = client.get("/api/exams/readiness").json()
    assert min(ready["unseen"].values()) < 20 and ready["full_mocks_available"] == 0 and not ready["can_generate"]


def test_unopened_paper_is_replaced_not_stacked(client, db):
    fresh_student(client)
    first = client.post("/api/exams/attempts", json={"mode": "subject", "subject": "Physics", "count": 5}).json()["id"]
    r2 = client.post("/api/exams/attempts", json={"mode": "subject", "subject": "Chemistry", "count": 5})
    assert r2.status_code == 201, r2.text
    second = r2.json()["id"]
    listed = client.get("/api/exams/attempts").json()
    assert len(listed) == 1 and listed[0]["id"] == second and listed[0]["title"] == "Chemistry practice"
    assert first  # (SQLite may reuse the deleted paper's id, so compare by content)
    assert client.post(f"/api/exams/attempts/{second}/submit").status_code == 409  # cannot submit an unopened booklet


def test_reported_questions_are_hidden_after_two_reports(client, db):
    from app.models import User
    from app.services import exams
    fresh_student(client)
    aid = paper(client, mode="subject", subject="Botany", count=10)
    assert client.post(f"/api/exams/attempts/{aid}/report/1", json={"reason": "wrong_answer"}).status_code == 409  # not yet
    client.post(f"/api/exams/attempts/{aid}/submit")
    attempt = db.get(ExamAttempt, aid)
    # Expert-reviewed questions are never auto-hidden; pick an unreviewed sample question.
    pos, q = next((i.position, i.question) for i in attempt.items if i.question.review_status == "sample")
    r = client.post(f"/api/exams/attempts/{aid}/report/{pos}", json={"reason": "wrong_answer", "note": "Key looks wrong"})
    assert r.status_code == 200 and not r.json()["already_reported"]
    assert client.post(f"/api/exams/attempts/{aid}/report/{pos}", json={"reason": "typo"}).json()["already_reported"]
    other = db.scalar(select(User).where(User.email == "admin@demo.test"))
    db.expire_all()  # the API changed the row in its own session
    exams.report_question(db, db.get(ExamAttempt, aid), pos, other, "unclear", None)  # a second, different student
    db.refresh(q)
    assert q.report_count == 2 and q.review_status == "flagged"
    assert q.id not in {x.id for x in exams._unseen(db, other.id, Question.subject == "Botany")}  # no longer served
