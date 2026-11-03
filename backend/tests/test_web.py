"""The server-rendered website: pages render, forms validate, and HTMX actions save through the API rules."""
import re

import pytest
from sqlalchemy import select

from app.web.routes_assistant import chat_text
from app.web.routes_practice import stem_html
from app.web.routes_student import score_chart

HX = {"HX-Request": "true"}


@pytest.mark.parametrize("path", ["/", "/colleges", "/colleges?state=Delhi", "/predictor", "/neet", "/careers",
                                  "/compare", "/counselling", "/login", "/register", "/privacy", "/terms"])
def test_public_pages_render(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert "NEET Compass gives guidance, not guarantees." in r.text


@pytest.mark.parametrize("path", ["/dashboard", "/profile", "/study-plan", "/mock-tests", "/practice", "/assistant"])
def test_student_pages_need_sign_in(client, path):
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")


def test_college_detail_tabs(client):
    for tab in ["overview", "admission", "fees", "hostel", "academics", "outcomes", "campus", "around"]:
        assert client.get(f"/colleges/1?tab={tab}").status_code == 200
    assert client.get("/colleges/999999").status_code == 404
    # Switching tabs swaps the tab bar too, so the highlighted tab follows the content.
    html = client.get("/colleges/1?tab=fees").text
    assert 'hx-target="#college-tabs"' in html
    bar = html.split('id="college-tabs"', 1)[1].split('id="tab-region"', 1)[0]
    assert 'aria-selected="true" href="/colleges/1?tab=fees"' in bar


def test_predictor_form_and_validation(client):
    r = client.post("/predictor", data={"course_code": "MBBS", "exam_year": "2025", "rank_type": "official",
                                        "air": "9000", "quotas": ["AIQ", "STATE"]}, headers=HX)
    assert r.status_code == 200 and "Historical cutoffs" in r.text
    assert not re.search(r"\d+\s?% chance|guaranteed seat", r.text, re.I)
    r = client.post("/predictor", data={"exam_year": "1990", "air": "9000"}, headers=HX)
    assert r.status_code == 422


def test_unsafe_requests_need_csrf(student):
    from fastapi.testclient import TestClient
    from app.main import app
    raw = TestClient(app, cookies=student.cookies)  # no X-CSRF-Token header
    assert raw.post("/roadmap/generate").status_code == 403


def test_save_toggle_and_review(student):
    first = student.post("/saved/1/toggle", headers=HX).text
    second = student.post("/saved/1/toggle", headers=HX).text
    assert {"★ Saved" in first, "★ Saved" in second} == {True, False}
    assert student.post("/colleges/1/reviews", data={"rating": "4", "body": "short"}, headers=HX).status_code == 422
    r = student.post("/colleges/1/reviews", data={"rating": "4", "body": "Good clinical exposure and a helpful library."}, headers=HX)
    assert "after moderation" in r.text


def test_profile_forms(student):
    r = student.post("/profile", data={"display_name": "Test", "category": "XYZ"}, headers=HX)
    assert r.status_code == 422 and "Unknown category" in r.text
    r = student.post("/profile", data={"display_name": "Test", "current_class": "12"}, headers=HX)
    assert "Profile saved." in r.text
    r = student.post("/profile/exam", data={"exam_year": "2025", "taken": "yes", "rank_type": "estimated",
                                            "estimated_rank_low": "9000", "estimated_rank_high": "5000"}, headers=HX)
    assert r.status_code == 422


def test_study_plan_and_syllabus(student):
    r = student.post("/study-plan", data={"current_class": "12", "weekday_hours": "4", "weekend_hours": "7"}, headers=HX)
    assert r.status_code == 200 and "This week" in r.text
    task = re.search(r"/study-plan/tasks/(\d+)", r.text).group(1)
    assert student.post(f"/study-plan/tasks/{task}", data={"done": "1"}, headers=HX).status_code == 200
    chapter = re.search(r"/syllabus/(\d+)", r.text).group(1)
    assert student.post(f"/syllabus/{chapter}", data={"status": "revised"}, headers=HX).status_code == 200


def test_mock_test_log(student):
    r = student.post("/mock-tests", data={"name": "T", "test_date": "2026-01-10", "total_score": "900"}, headers=HX)
    assert r.status_code == 422 and "exceed" in r.text
    r = student.post("/mock-tests", data={"name": "T", "test_date": "2026-01-10", "total_score": "500",
                                          "Physics": "120", "Physics-topics": "Optics"}, headers=HX)
    assert "<polyline" in r.text
    tid = re.findall(r'hx-delete="/mock-tests/(\d+)"', r.text)[0]
    assert student.delete(f"/mock-tests/{tid}", headers=HX).status_code == 200


def test_exam_flow(student):
    r = student.post("/practice/prepare", data={"mode": "mini", "per_section": "5"}, headers=HX)
    aid = r.headers["hx-redirect"].rsplit("/", 1)[1]
    page = student.get(f"/practice/{aid}?step=3").text
    roll = re.search(r"admit card: (\d+)", page).group(1)
    code = re.search(r'tracking-widest">(\w\d)<', page).group(1)
    bad = student.post(f"/practice/{aid}/start", data={"roll": "1", "series": code[0], "num": code[1]}, headers=HX)
    assert bad.status_code == 422
    r = student.post(f"/practice/{aid}/start", data={"roll": roll, "series": code[0], "num": code[1]}, headers=HX)
    assert r.headers["hx-retarget"] == "#exam-day" and 'id="exam-room"' in r.text
    r = student.post(f"/practice/{aid}/act", data={"cur": "0", "op": "choose", "target": "0", "option": "1", "elapsed": "5"}, headers=HX)
    assert 'aria-label="Question 1, option 2" aria-pressed="true"' in r.text
    r = student.post(f"/practice/{aid}/act", data={"cur": "0", "op": "go", "target": "4"}, headers=HX)
    assert 'data-cur="4"' in r.text
    assert student.post(f"/practice/{aid}/submit", headers=HX).headers["hx-redirect"] == f"/practice/{aid}"
    assert "Scorecard" in student.get(f"/practice/{aid}").text


def test_counselling_draft_builder(student):
    base = {"authority": "MCC", "air": "20000", "year": "2025",
            "priorities": ["government_first", "preferred_states", "lower_cost", "fit"]}
    r = student.post("/counselling/draft", data={**base, "op": "prio:0:1"}, headers=HX)
    assert re.findall(r'name="priorities" value="(\w+)"', r.text)[:2] == ["preferred_states", "government_first"]
    r = student.post("/counselling/draft", data={**base, "op": "build"}, headers=HX)
    assert r.status_code == 200 and "draft_json" in r.text


def test_assistant_chat(student):
    r = student.post("/assistant/send", data={"content": "How does AIQ differ from state quota?"}, headers=HX)
    assert r.status_code == 200 and r.headers["hx-push-url"].startswith("/assistant?chat=")
    sid = r.headers["hx-push-url"].split("=")[1]
    assert student.post("/assistant/send", data={"content": "", "session_id": sid}, headers=HX).status_code == 422
    assert student.post(f"/assistant/{sid}/delete", data={"current": sid}, headers=HX).headers["hx-push-url"] == "/assistant"


def test_admin_pages_are_admin_only(student):
    r = student.get("/admin", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/login"


def test_admin_login_page(client):
    assert "Admin sign-in" in client.get("/admin/login").text
    assert client.get("/admin", follow_redirects=False).headers["location"] == "/admin/login"
    bad = client.post("/admin/login", data={"email": "student@demo.test", "password": "demo-password-123"})
    assert bad.status_code == 401 and "not an admin" in bad.text  # right password, but not an admin
    assert client.post("/admin/login", data={"email": "admin@demo.test", "password": "wrong"}).status_code == 401
    ok = client.post("/admin/login", data={"email": "admin@demo.test", "password": "demo-password-123"}, follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == "/admin"
    assert "Students" in client.get("/admin").text and "Ward rounds" in client.get("/admin").text


def test_admin_tabs_and_actions(admin):
    for tab in ["overview", "imports", "sources", "rules", "info", "colleges", "issues"]:
        assert admin.get(f"/admin?tab={tab}").status_code == 200
    r = admin.post("/admin/sources/source", data={"code": "x", "name": "ab", "kind": "other"}, headers=HX)
    assert r.status_code == 422


def test_text_helpers_escape_html():
    assert "<script>" not in chat_text("**hi** <script>alert(1)</script>")
    assert "<strong>hi</strong>" in chat_text("**hi**")
    table = stem_html("Match:\nA. Heart | I. Pump\nB. Lung | II. Gas exchange\nChoose.")
    assert "List-I" in table and "<td" in table
    assert "&lt;b&gt;" in stem_html("<b>x</b>")


def test_score_chart_layout():
    chart = score_chart([{"test_date": "2026-01-01", "percent": 50, "subjects": {"Physics": 40}},
                         {"test_date": "2026-02-01", "percent": 75, "subjects": {}}])
    total = next(s for s in chart["series"] if s["name"] == "Total")
    assert len(total["dots"]) == 2 and total["dots"][0]["y"] > total["dots"][1]["y"]  # higher score sits higher


def test_admin_console_and_student_file(admin, db):
    from app.models import AuditLog, StudentProfile, User
    student = db.scalar(select(User).where(User.email == "student@demo.test"))
    prof = db.scalar(select(StudentProfile).where(StudentProfile.user_id == student.id))
    if prof is None:
        prof = StudentProfile(user_id=student.id)
        db.add(prof)
    prof.category, prof.pwd = "OBC", True
    db.commit()
    overview = admin.get("/admin").text
    assert "Ward rounds" in overview and "Go-live checklist" in overview
    assert "Student register" in admin.get("/admin?tab=users").text
    r = admin.get(f"/admin/students/{student.id}")
    assert r.status_code == 200 and "Student file" in r.text and "Attendance" in r.text
    assert "OBC" not in r.text  # category is never shown to admins
    assert db.scalar(select(AuditLog).where(AuditLog.action == "view_student", AuditLog.entity_id == student.id))
    assert admin.get("/admin/students/999999").status_code == 404


def test_student_cannot_open_student_files(student):
    r = student.get("/admin/students/1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/login"


def test_static_files_are_cacheable_and_pages_need_no_other_servers(client):
    page = client.get("/").text
    css = re.search(r'href="(/static/app\.css\?v=\d+)"', page).group(1)
    assert client.get(css).headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/static/mascot/idle-still.png").headers["cache-control"] == "public, max-age=86400"
    assert "cache-control" not in client.get("/login").headers  # pages themselves are always fresh
    assert "googleapis" not in page and "jsdelivr" not in page
    assert client.get("/static/vendor/htmx-2.0.4.min.js?v=2.0.4").status_code == 200
    assert client.get("/static/fonts/plus-jakarta-sans-latin.woff2").status_code == 200
