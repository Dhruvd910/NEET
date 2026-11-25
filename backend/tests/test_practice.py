"""Practice tests (NEET format), syllabus progress, class-based study plans and nearby facilities."""
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.models import College, ExamAttempt, MockTest, Question, SyllabusChapter
from app.practice_seed import _hash
from app.services import exams, study_plan
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
    first: set[int] = set()
    while min(client.get("/api/exams/readiness").json()["unseen"].values()) >= 20:  # until the bank is used up
        aid = paper(client, mode="mini", count=20)
        ids = {i.question_id for i in db.get(ExamAttempt, aid).items}
        assert not ids & seen, "a question was repeated"
        first = first or ids
        seen |= ids
        client.post(f"/api/exams/attempts/{aid}/submit")
    assert len(seen) >= 80
    # The bank is used up and question writing is off (as in tests): never-seen questions come first, then the
    # ones seen longest ago, instead of refusing or costing money.
    r = client.post("/api/exams/attempts", json={"mode": "mini", "count": 20})
    assert r.status_code == 201, r.text
    again = {i.question_id for i in db.get(ExamAttempt, r.json()["id"]).items}
    assert again & first  # the repeats are the oldest ones
    ready = client.get("/api/exams/readiness").json()
    assert min(ready["unseen"].values()) < 20 and not ready["can_generate"]


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


def test_learning_progress_and_estimate(client, db):
    from app.services import learning
    fresh_student(client)
    user_id = client.get("/api/auth/me").json()["id"]
    physics = db.scalars(select(SyllabusChapter).where(SyllabusChapter.subject == "Physics")).all()
    for c in physics[:2]:
        client.put(f"/api/syllabus/progress/{c.id}", json={"status": "mastered"})
    client.put(f"/api/syllabus/progress/{physics[2].id}", json={"status": "learning"})
    p = learning.progress(db, user_id)
    phy = next(s for s in p["subjects"] if s["name"] == "Physics")
    hours = sum(c.est_hours for c in physics)
    done = physics[0].est_hours + physics[1].est_hours + physics[2].est_hours / 2
    assert phy["covered"] == 2 and phy["percent"] == round(100 * done / hours)
    # Pace: all of it happened today, so the window is the 7-day minimum.
    assert p["pace_window_days"] == 7 and phy["eta"]["days"] == round((hours - done) / (done / 7))
    assert next(s for s in p["subjects"] if s["name"] == "Chemistry")["eta"] is None  # nothing done, no guess
    assert p["overall"]["last"] is not None
    assert "Learning progress" in client.get("/dashboard").text


def test_daily_quiz_once_a_day(client, db):
    fresh_student(client)
    r = client.post("/api/exams/attempts", json={"mode": "daily"})
    assert r.status_code == 201, r.text
    assert r.json()["questions"] == 5
    aid = r.json()["id"]
    client.post(f"/api/exams/attempts/{aid}/start")
    client.post(f"/api/exams/attempts/{aid}/submit")
    again = client.post("/api/exams/attempts", json={"mode": "daily"})
    assert again.status_code == 422 and "today's quiz" in again.text
    assert "/practice/%d" % aid in client.get("/dashboard").text  # the dashboard links to today's result


def test_daily_quiz_game_lives_combo_xp(client, db):
    from app.services import game
    fresh_student(client)
    aid = client.post("/api/exams/attempts", json={"mode": "daily"}).json()["id"]
    assert "Lock in" in client.get(f"/practice/{aid}").text  # straight into the game: no admit card or OMR sheet
    a = db.get(ExamAttempt, aid)
    db.refresh(a)
    items = sorted(a.items, key=lambda i: i.position)
    assert {i.section for i in items} == set(exams.SECTIONS)  # every subject, one twice
    play = lambda pos, opt: client.post(f"/practice/{aid}/play/{pos}", data={"option": opt})
    right = lambda it: it.correct_index
    wrong = lambda it: (it.correct_index + 1) % 4
    r = play(1, right(items[0])).text
    assert "Correct!" in r and "+10 XP" in r
    r = play(2, right(items[1])).text
    assert "+20 XP" in r and "combo ×2" in r  # the second in a row counts double
    assert play(1, wrong(items[0])).headers.get("hx-redirect") == f"/practice/{aid}"  # an answer cannot be changed
    assert "Pick an answer" in client.post(f"/practice/{aid}/play/3", data={}).text
    for pos in (3, 4):
        assert "Not quite" in play(pos, wrong(items[pos - 1])).text
    assert "Game over" in play(5, wrong(items[4])).text  # third wrong answer: out of lives
    db.expire_all()
    a = db.get(ExamAttempt, aid)
    g = game.run(a)
    assert a.status == "submitted" and g["hearts"] == 0 and g["xp"] == 10 + 20 + game.FINISH_BONUS and a.score == 8 - 3
    page = client.get(f"/practice/{aid}").text
    assert "+50 XP" in page and "Level 1" in page and "★" in page
    assert game.streak(db, a.user_id) == 1
    assert "Lv 1" in client.get("/dashboard").text


def test_previous_year_papers_are_separate_from_mocks(admin, client, db):
    tag = uuid.uuid4().hex[:6]
    csv_text = ("chapter_code,difficulty,question,option_1,option_2,option_3,option_4,answer,pyq_year\n"
                f"PHY-12-03,medium,PYQ one {tag},1 A,2 A,3 A,4 A,2,2019\n"
                f"CHE-11-01,medium,PYQ two {tag},a,b,c,d,3,2019\n"
                f"PHY-12-03,medium,Bad year {tag},a,b,c,d,1,1999\n")
    r = admin.post("/api/admin/questions/import", data={"data_source_code": "DEMO", "source_name": "NEET 2019 paper",
                                                        "expert_reviewed": "true"},
                   files={"file": ("pyq.csv", csv_text.encode(), "text/csv")})
    assert (r.json()["inserted"], r.json()["skipped"]) == (2, 1)
    pyq_ids = set(db.scalars(select(Question.id).where(Question.pyq_year == 2019)))

    fresh_student(client)
    r = client.post("/api/exams/attempts", json={"mode": "pyq", "year": 2019})
    assert r.status_code == 201, r.text
    a = db.get(ExamAttempt, r.json()["id"])
    assert a.title == "NEET 2019 paper" and {i.question_id for i in a.items} == pyq_ids
    assert [i.section for i in a.items] == ["Physics", "Chemistry"]  # paper order
    assert client.post("/api/exams/attempts", json={"mode": "pyq", "year": 2018}).status_code == 422  # none added
    # Mocks never use them.
    m = client.post("/api/exams/attempts", json={"mode": "mini", "count": 5}).json()
    db.expire_all()  # the unopened past paper was replaced, and SQLite may reuse its id
    assert not pyq_ids & {i.question_id for i in db.get(ExamAttempt, m["id"]).items}


def test_question_versions_never_share_a_paper(db, monkeypatch):
    import random
    import re

    from app.config import get_settings
    from app.models import ExamAttemptItem, User
    from app.services import exams, variants
    ch = db.scalars(select(SyllabusChapter).where(SyllabusChapter.subject == "Physics")).first()
    topic = uuid.uuid4().hex
    uid = db.scalars(select(User.id)).first()

    def q(stem, of=None):
        x = Question(subject="Physics", chapter_id=ch.id, topic=topic, stem=stem, options=["1 N", "2 N", "3 N", "4 N"],
                     correct_index=1, review_status="reviewed", content_hash=_hash(stem + topic, []), variant_of=of,
                     source_name="test")
        db.add(x)
        db.flush()
        return x

    a, b = q("A 2 kg body at 10 m/s stops in 4 s. Force?"), q("Unrelated question")
    a2 = q("A 4 kg body at 15 m/s stops in 5 s. Force?", a.id)
    mine = Question.topic == topic
    assert {x.id for x in exams._unseen(db, uid, mine, need=2)} == {a.id, b.id}  # one version each, the original
    att = ExamAttempt(user_id=uid, mode="mini", title="t", duration_seconds=60, max_score=4,
                      deadline_at=datetime.now(timezone.utc), status="submitted")
    db.add(att)
    db.flush()
    db.add(ExamAttemptItem(attempt_id=att.id, question_id=a.id, position=1, section="Physics", correct_index=1))
    db.flush()
    assert [x.id for x in exams._unseen(db, uid, mine, need=1)] == [b.id]  # brand-new questions first
    assert {x.id for x in exams._unseen(db, uid, mine, need=2)} == {b.id, a2.id}  # then a new version, not a repeat

    # The free-model job keeps a version only when the checker reaches the writer's answer.
    s = get_settings()
    writer = {"stem": "A 3 kg body at 12 m/s stops in 4 s. Force?", "options": ["3 N", "6 N", "9 N", "12 N"],
              "answer": 3, "explanation": "3 x 3"}
    agree = {"confident": True, "unambiguous": True, "in_syllabus": True}

    def ask(right):
        def fake(client, model, prompt, t):
            if model == s.variant_writer_model:
                return writer
            shown = re.findall(r"^(\d)\. (.*)$", prompt, re.M)  # options after shuffling
            n = next(int(i) for i, o in shown if o == "9 N")
            return {**agree, "answer": n if right else n % 4 + 1}
        return fake

    monkeypatch.setattr(variants, "_ask", ask(right=False))
    assert variants.make_variant(db, b, None, random.Random(1)) == "checker disagreed"
    monkeypatch.setattr(variants, "_ask", ask(right=True))
    assert variants.make_variant(db, b, None, random.Random(1)) == "kept"
    v = db.scalar(select(Question).where(Question.variant_of == b.id))
    assert v.options[v.correct_index] == "9 N" and v.review_status == "ai_checked" and v.pyq_year is None
