import uuid

from sqlalchemy import select

from app.models import College, CutoffRecord, VerificationStatus
from tests.conftest import PASSWORD


def register(client, minor=False, guardian_email=None):
    email = f"s-{uuid.uuid4().hex[:8]}@example.test"
    return email, client.post("/api/auth/register", json={
        "email": email, "password": PASSWORD, "is_minor": minor, "guardian_email": guardian_email,
        "accept_privacy_notice": True})


def test_minor_needs_guardian_email(client):
    _, r = register(client, minor=True)
    assert r.status_code == 422 and "guardian" in r.json()["detail"]
    _, r = register(client, minor=True, guardian_email="parent@example.test")
    assert r.status_code == 201 and r.json()["guardian_consent_status"] == "pending"


def test_auth_required_and_wrong_password(client):
    assert client.get("/api/profile").status_code == 401
    r = client.post("/api/auth/login", json={"email": "student@demo.test", "password": "wrong-password"})
    assert r.status_code == 401


def test_profile_and_exam_validation(client):
    register(client)
    r = client.put("/api/profile", json={"display_name": "A", "category": "GEN", "domicile_state": "Karnataka"})
    assert r.status_code == 200 and r.json()["category"] == "OPEN"
    assert client.put("/api/profile", json={"category": "XYZ"}).status_code == 422
    # Estimated ranks must not be stored as official AIR
    r = client.put("/api/exam-profiles", json={"exam_year": 2026, "rank_type": "estimated", "air": 5000})
    assert r.status_code == 422
    r = client.put("/api/exam-profiles", json={"exam_year": 2026, "rank_type": "estimated",
                                               "estimated_rank_low": 4000, "estimated_rank_high": 7000})
    assert r.status_code == 200


def test_students_cannot_use_admin(student):
    assert student.get("/api/admin/stats").status_code == 403
    assert student.post("/api/admin/verify", json={"entity_type": "college", "entity_id": 1,
                                                   "status": "verified"}).status_code == 403


def test_demo_data_is_never_presented_as_verified(client, db):
    demo = db.scalars(select(College).where(College.is_demo.is_(True))).all()
    assert demo and all(c.verification_status == VerificationStatus.demo and "(DEMO)" in c.name or "(TEST)" in c.name
                        for c in demo)
    items = client.get("/api/colleges", params={"page_size": 100}).json()["items"]
    for card in items:
        if card["is_demo"]:
            assert card["verification_status"] == "demo"
            assert not (card["fee_summary"] or {}).get("verified")
    detail = client.get(f"/api/colleges/{demo[0].id}").json()
    assert detail["overview"]["is_demo"] and detail["overview"]["verification_status"] == "demo"
    assert all(cut["verification_status"] == "demo" for cut in detail["admission"]["cutoffs"])


def test_admin_cannot_verify_demo_records(admin, db):
    rec = db.scalars(select(CutoffRecord).where(CutoffRecord.verification_status == VerificationStatus.demo)).first()
    r = admin.post("/api/admin/verify", json={"entity_type": "cutoff_record", "entity_id": rec.id, "status": "verified"})
    assert r.status_code == 422
    r = admin.post("/api/admin/verify", json={"entity_type": "cutoff_record", "entity_id": rec.id, "status": "outdated"})
    assert r.status_code == 200
    assert admin.get("/api/admin/audit").json()[0]["action"] == "set_verification"


def test_college_detail_has_provenance_and_costs(client, db):
    c = db.scalars(select(College).where(College.code == "DEMO-KA-GOV-A")).one()
    d = client.get(f"/api/colleges/{c.id}").json()
    for key in ("source_name", "verification_status", "collected_at"):
        assert key in d["overview"]
    assert d["admission"]["cutoffs"][0]["exam_year"]
    cost = d["costs"]["MBBS"]
    assert cost["academic_year"] == "2025-26" and cost["fee_lines"][0]["verification_status"] == "demo"
    assert "Not verified" in d["reviews"]["label"] or "Not verified facts" in d["reviews"]["label"]
    assert client.get("/api/colleges/999999").status_code == 404


def test_predict_endpoint(client):
    r = client.post("/api/predict", json={"exam_year": 2026, "air": 9000, "category": "OPEN",
                                          "quotas": ["AIQ"], "course_code": "MBBS"})
    assert r.status_code == 200
    body = r.json()
    assert set(body["groups"]) == {"Stronger historical fit", "Possible / uncertain", "Ambitious"}
    assert "not predictions of admission" in body["disclaimer"]
    for group in body["groups"].values():
        for row in group:
            assert row["quota"] == "AIQ" and row["counselling_authority"] == "MCC"
            assert "safe" not in row["explanation"].lower()
    assert client.post("/api/predict", json={"exam_year": 2026}).status_code == 422


def test_compare(client, db):
    ids = [c.id for c in db.scalars(select(College).where(College.code.like("DEMO-%"))).all()[:3]]
    r = client.post("/api/compare", json={"college_ids": ids, "priorities": ["cost", "cutoff", "hostel"]})
    assert r.status_code == 200
    body = r.json()
    assert len(body["colleges"]) == 3 and body["insights"] and "universal" in body["note"]
    assert client.post("/api/compare", json={"college_ids": ids[:1]}).status_code == 422


def test_mock_tests_flow(student):
    r = student.post("/api/mock-tests", json={"name": "T", "test_date": "2025-12-01", "total_score": 800, "max_score": 720})
    assert r.status_code == 422
    r = student.post("/api/mock-tests", json={
        "name": "Weekly", "test_date": "2025-12-01", "total_score": 600, "max_score": 720,
        "subjects": [{"subject": "Physics", "score": 120, "max_score": 180, "weak_topics": ["Optics"]}]})
    assert r.status_code == 201
    a = student.get("/api/mock-tests/analytics").json()
    assert a["count"] >= 1 and "not official" in a["notice"].lower()


def test_preference_draft_is_draft_and_follows_priorities(client):
    r = client.post("/api/preference-lists/draft", json={
        "authority_code": "MCC", "priorities": ["lower_cost", "fit"],
        "predict": {"exam_year": 2026, "air": 30000, "category": "OPEN", "quotas": ["AIQ", "DEEMED"]}})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "draft" and "not submitted" in body["notice"]
    costs = [i["estimated_annual_cost_inr"] for i in body["items"] if i["estimated_annual_cost_inr"] is not None]
    assert costs == sorted(costs)


def test_assistant_fallback_is_grounded(student):
    r = student.post("/api/assistant/messages", json={"content": "Which colleges are realistic for my rank?"})
    assert r.status_code == 200
    body = r.json()
    assert body["backend"] == "rules"
    msg = body["message"]
    assert "predict_colleges" in msg["tool_calls"] and "guarantee" in msg["content"].lower()
    r = student.post("/api/assistant/messages", json={"session_id": body["session_id"],
                                                      "content": "How does AIQ differ from state quota?"})
    assert "search_documents" in r.json()["message"]["tool_calls"]
    assert r.json()["message"]["citations"]


def test_review_goes_to_moderation(student, db):
    cid = db.scalars(select(College.id)).first()
    r = student.post(f"/api/colleges/{cid}/reviews", json={"rating": 4, "body": "x" * 40})
    assert r.status_code == 202 and r.json()["status"] == "pending"


def test_account_export_and_deletion(client):
    register(client)
    client.put("/api/profile", json={"display_name": "Temp"})
    exported = client.get("/api/auth/me/export").json()
    assert exported["student_profiles"][0]["display_name"] == "Temp"
    assert client.delete("/api/auth/me").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
