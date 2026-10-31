"""Data pipeline for real-world data: source terms gate, seat-matrix/fee importers, eligibility rules,
info-page review, OCR, semantic search, nearby places and the go-live readiness checklist.

Colleges created here are synthetic test records (code "RT-…", name "… (TEST)").
"""
import io
import shutil
import uuid

import pytest
from sqlalchemy import select

from app.models import (
    College, DataQualityIssue, DataSource, DocumentChunk, FeeRecord, InfoArticle, NearbyPlace, SeatMatrix,
    SourceDocument, VerificationStatus,
)
from app.services import embeddings, ingestion, ocr, places, retrieval
from app.services.costs import estimate_cost
from tests.fixtures import ensure_authority


def _real_college(admin, state="Rulestate", lat=None, lon=None) -> int:
    code = f"RT-{uuid.uuid4().hex[:6]}"
    r = admin.post("/api/admin/colleges", json={
        "code": code, "name": f"Realistic Test College {code} (TEST)", "state": state,
        "institution_type": "government", "source_name": "Test registry", "latitude": lat, "longitude": lon})
    assert r.status_code == 201, r.text
    return r.json()["id"], code


def _upload(admin, kind, csv_text, source="DEMO", name="Test import"):
    return admin.post(f"/api/admin/imports/{kind}", data={"data_source_code": source, "source_name": name,
                                                          "source_url": "https://example.org/official.pdf"},
                      files={"file": ("data.csv", csv_text.encode(), "text/csv")})


def _allow_source(admin, db, code):
    sid = db.scalar(select(DataSource.id).where(DataSource.code == code))
    r = admin.patch(f"/api/admin/data-sources/{sid}/terms", json={
        "usage_status": "allowed", "terms_url": "https://example.org/terms",
        "terms_note": "Reviewed for test: public notices may be reused with attribution."})
    assert r.status_code == 200


def test_import_refused_until_source_terms_reviewed(admin, db):
    _, code = _real_college(admin)
    csv_text = f"college_code,course,authority,exam_year,round,quota,category,seats\n{code},MBBS,KEA,2025,1,STATE,UR,10\n"
    r = _upload(admin, "seat_matrix", csv_text, source="KEA")
    assert r.status_code == 422 and "terms-of-use" in r.json()["detail"]
    assert _upload(admin, "seat_matrix", csv_text, source="NOPE").status_code == 422
    _allow_source(admin, db, "KEA")
    r = _upload(admin, "seat_matrix", csv_text, source="KEA")
    assert r.status_code == 200 and r.json()["inserted"] == 1
    doc = db.scalar(select(SourceDocument).order_by(SourceDocument.id.desc()))
    assert doc.data_source_id == db.scalar(select(DataSource.id).where(DataSource.code == "KEA"))


def test_seat_matrix_import_validates_and_is_idempotent(admin, db):
    cid, code = _real_college(admin)
    csv_text = ("college_code,course,authority,exam_year,round,quota,category,seat_type,seats\n"
                f"{code},MBBS,MCC,2025,1,AIQ,UR,,15\n"
                f"{code},MBBS,MCC,2025,1,AIQ,OBC-NCL,,8\n"
                f"{code},MBBS,MCC,2025,1,AIQ,OBC,PwD,1\n"
                f"{code},MBBS,MCC,2025,1,STATE,UR,,5\n"      # MCC does not run state quota
                f"{code},MBBS,MCC,2025,1,AIQ,SC,,-3\n"
                "NOPE-1,MBBS,MCC,2025,1,AIQ,UR,,4\n")
    job = _upload(admin, "seat_matrix", csv_text).json()
    assert (job["inserted"], job["skipped"], job["status"]) == (3, 3, "partial")
    rows = db.scalars(select(SeatMatrix).where(SeatMatrix.college_id == cid)).all()
    assert {(r.category, r.seat_type, r.seats) for r in rows} == {("OPEN", "GENERAL", 15), ("OBC", "GENERAL", 8),
                                                                   ("OBC", "PWD", 1)}
    assert all(r.verification_status == VerificationStatus.unverified for r in rows)
    again = _upload(admin, "seat_matrix", csv_text).json()
    assert again["inserted"] == 0 and again["updated"] == 0


def test_fee_import_feeds_cost_estimate(admin, db):
    cid, code = _real_college(admin)
    csv_text = ("college_code,course,academic_year,quota,fee_type,amount_inr,period,mandatory,refundable,note\n"
                f"{code},MBBS,2025-26,ALL,tuition,\"1,20,000\",annual,yes,no,\n"
                f"{code},MBBS,2025-26,ALL,hostel,3000,monthly,yes,no,Shared room\n"
                f"{code},MBBS,2025-26,ALL,security_deposit,10000,one_time,yes,,\n"
                f"{code},MBBS,2025-27,ALL,tuition,5000,annual,yes,no,\n"       # bad academic year
                f"{code},MBBS,2025-26,ALL,donation,5000,annual,yes,no,\n")      # unknown fee type
    job = _upload(admin, "fees", csv_text).json()
    assert (job["inserted"], job["skipped"]) == (3, 2)
    errors = " ".join(e["error"] for e in job["errors"])
    assert "academic_year" in errors and "fee_type" in errors
    deposit = db.scalar(select(FeeRecord).where(FeeRecord.college_id == cid, FeeRecord.fee_type == "security_deposit"))
    assert deposit.refundable  # deposits default to refundable
    est = estimate_cost(db, cid)
    assert est.academic_year == "2025-26" and est.estimated_annual_total_inr == 120000 + 3000 * 12
    assert est.refundable_deposits_inr == 10000

    changed = csv_text.replace("3000,monthly", "3500,monthly")
    assert _upload(admin, "fees", changed).json()["updated"] == 1


def _predict_obc(client):
    return client.post("/api/predict", json={"exam_year": 2026, "air": 20000, "category": "OBC", "quotas": ["AIQ"],
                                             "preferred_states": ["Openstate"]}).json()


def test_open_seat_rule_needs_verification_before_use(admin, client, db):
    # A test authority keeps this independent of the demo rules seeded for MCC.
    ensure_authority(db, code="TST-AIQ", state=None).quotas = ["AIQ"]
    db.commit()
    cid, code = _real_college(admin, state="Openstate")
    rows = "".join(f"{code},MBBS,TST-AIQ,{y},2,AIQ,UR,{c}\n" for y, c in ((2023, 21000), (2024, 22000), (2025, 23000)))
    _upload(admin, "cutoffs", "college_code,course,authority,exam_year,round,quota,category,closing_rank\n" + rows)

    def listed():
        return any(r["college_id"] == cid for g in _predict_obc(client)["groups"].values() for r in g)

    assert not listed()  # no rule: OBC student is not compared with OPEN cutoffs
    gaps = admin.get("/api/admin/eligibility-rules").json()["gaps"]
    assert any(g["authority"] == "TST-AIQ" and g["exam_year"] == 2025 and g["quota"] == "AIQ" for g in gaps)

    mcc = next(a for a in admin.get("/api/admin/eligibility-rules").json()["authorities"] if a["code"] == "TST-AIQ")
    r = admin.put("/api/admin/eligibility-rules", json={
        "authority_id": mcc["id"], "exam_year": 2025, "quota": "AIQ", "rule_key": "open_category_accessible",
        "value": True, "source_name": "MCC counselling scheme (test)", "source_url": "https://example.org/scheme.pdf"})
    assert r.status_code == 200 and r.json()["verification_status"] == "unverified"
    assert not listed()  # an unverified rule is not used

    assert admin.post("/api/admin/verify", json={"entity_type": "eligibility_rule", "entity_id": r.json()["id"],
                                                 "status": "verified"}).status_code == 200
    assert listed()
    gaps = admin.get("/api/admin/eligibility-rules").json()["gaps"]
    assert not any(g["authority"] == "TST-AIQ" and g["exam_year"] == 2025 and g["quota"] == "AIQ" for g in gaps)

    bad = admin.put("/api/admin/eligibility-rules", json={
        "authority_id": mcc["id"], "exam_year": 2025, "quota": "STATE", "rule_key": "open_category_accessible",
        "value": True, "source_name": "x" * 5, "source_url": "https://example.org/a"})
    assert bad.status_code == 422


def test_info_article_review_workflow(admin, db):
    art = db.scalar(select(InfoArticle).where(InfoArticle.slug == "neet-pattern"))
    r = admin.post("/api/admin/verify", json={"entity_type": "info_article", "entity_id": art.id, "status": "verified"})
    assert r.status_code == 422 and "exam year" in r.json()["detail"]
    r = admin.patch(f"/api/admin/info-articles/{art.id}", json={"exam_year": 2026, "body": art.body + "\n\n(Checked.)"})
    assert r.status_code == 200 and r.json()["verification_status"] == "pending_review"
    r = admin.post("/api/admin/verify", json={"entity_type": "info_article", "entity_id": art.id, "status": "verified"})
    assert r.status_code == 200
    db.refresh(art)
    assert art.verification_status == VerificationStatus.verified and art.last_verified_at


def _blank_pdf() -> bytes:
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=595, height=842)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_scanned_pages_are_ocred_and_flagged_for_review(db, monkeypatch):
    monkeypatch.setattr(ocr, "ocr_available", lambda: True)
    monkeypatch.setattr(ocr, "ocr_pdf_pages", lambda content, pages: {p: "Scanned notice: stray vacancy round dates"
                                                                       for p in pages})
    doc = ingestion.ingest_document(db, _blank_pdf() + uuid.uuid4().bytes, "scan.pdf", title=f"Scan {uuid.uuid4()}",
                                    url=None, authority="MCC", doc_type="notice", exam_year=2025, state=None,
                                    publication_date=None)
    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id)).all()
    assert chunks and all(c.extraction == "ocr" for c in chunks)
    kinds = set(db.scalars(select(DataQualityIssue.issue_type).where(DataQualityIssue.entity_id == doc.id,
                                                                     DataQualityIssue.entity_type == "source_document")))
    assert kinds == {"ocr_text_needs_review"}


def test_missing_ocr_is_flagged_then_retried(admin, db, monkeypatch):
    monkeypatch.setattr(ocr, "ocr_available", lambda: False)
    doc = ingestion.ingest_document(db, _blank_pdf() + uuid.uuid4().bytes, "scan2.pdf", title=f"Scan {uuid.uuid4()}",
                                    url=None, authority=None, doc_type="notice", exam_year=None, state=None,
                                    publication_date=None)
    listed = next(d for d in admin.get("/api/admin/documents").json() if d["id"] == doc.id)
    assert listed["needs_ocr"] and listed["chunks"] == 0
    assert admin.post(f"/api/admin/documents/{doc.id}/ocr").status_code == 422

    monkeypatch.setattr(ocr, "ocr_available", lambda: True)
    monkeypatch.setattr(ocr, "ocr_pdf_pages", lambda content, pages: {p: "Recovered text" for p in pages})
    r = admin.post(f"/api/admin/documents/{doc.id}/ocr")
    assert r.status_code == 200 and r.json()["status"] == "succeeded"
    listed = next(d for d in admin.get("/api/admin/documents").json() if d["id"] == doc.id)
    assert not listed["needs_ocr"] and listed["chunks"] == 1


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract binary not installed")
def test_real_tesseract_reads_a_scanned_page():
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1240, 400), "white")
    ImageDraw.Draw(img).text((60, 150), "COUNSELLING NOTICE ROUND TWO", fill="black",
                             font=ImageFont.load_default(size=64))
    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=150)
    text = ocr.ocr_pdf_pages(buf.getvalue(), [1])[1]
    assert "COUNSELLING" in text.upper()


CONCEPTS = [("reservation", "quota", "category"), ("fee", "tuition", "money")]


def _fake_embed(texts, input_type):
    return [[float(any(w in t.lower() for w in words)) for words in CONCEPTS] + [0.1] for t in texts]


def test_bm25_prefers_specific_terms(db):
    scores = retrieval.bm25(["ews", "seats"], [retrieval.tokens("seats seats seats are listed"),
                                               retrieval.tokens("EWS seats are listed separately")])
    assert scores[1] > scores[0]


def test_semantic_search_finds_paraphrases(db, monkeypatch):
    monkeypatch.setattr(embeddings, "embeddings_enabled", lambda: True)
    monkeypatch.setattr(embeddings, "embed", _fake_embed)
    monkeypatch.setattr(retrieval, "embeddings_enabled", lambda: True)
    monkeypatch.setattr(retrieval, "embed", _fake_embed)
    title = f"Seat sharing note {uuid.uuid4().hex[:6]}"
    ingestion.ingest_document(db, f"Each state quota keeps a category-wise share.\n\n{uuid.uuid4()}".encode(),
                              "note.txt", title=title, url=None, authority="TSTSEM", doc_type="notice",
                              exam_year=None, state=None, publication_date=None)
    hits = retrieval.search_documents(db, "reservation rules", authority="TSTSEM")
    assert hits and hits[0]["title"] == title  # no shared keyword, found by meaning

    monkeypatch.setattr(retrieval, "embeddings_enabled", lambda: False)
    hits = retrieval.search_documents(db, "reservation rules", authority="TSTSEM")
    assert not [h for h in hits if h["kind"] == "document"]  # keyword-only search cannot find it


OVERPASS_SAMPLE = {"elements": [
    {"type": "node", "id": 1, "lat": 12.9720, "lon": 77.5950, "tags": {"highway": "bus_stop", "name": "Main Gate Stop"}},
    {"type": "node", "id": 2, "lat": 12.9800, "lon": 77.6000, "tags": {"amenity": "pharmacy", "name": "City Pharmacy"}},
    {"type": "way", "id": 3, "center": {"lat": 12.9900, "lon": 77.6100}, "tags": {"amenity": "hospital", "name": "General Hospital"}},
    {"type": "node", "id": 4, "lat": 12.9700, "lon": 77.5900, "tags": {"amenity": "pharmacy"}},  # unnamed: dropped
    {"type": "node", "id": 5, "lat": 12.9700, "lon": 77.5900, "tags": {"railway": "station", "station": "subway", "name": "Metro Stn"}},
]}


def test_overpass_parsing_and_refresh(admin, db):
    parsed = places.parse_overpass(OVERPASS_SAMPLE)
    assert {(p.kind, p.name) for p in parsed} == {("bus_stop", "Main Gate Stop"), ("pharmacy", "City Pharmacy"),
                                                  ("hospital", "General Hospital"), ("metro", "Metro Stn")}
    cid, _ = _real_college(admin, lat=12.9716, lon=77.5946)
    assert admin.post(f"/api/admin/colleges/{cid}/nearby/refresh").status_code == 422  # no provider configured

    college = db.get(College, cid)
    rows = places.refresh_nearby(db, college, fetch=lambda lat, lon: parsed)
    assert len(rows) == 4
    stop = db.scalar(select(NearbyPlace).where(NearbyPlace.college_id == cid, NearbyPlace.kind == "bus_stop"))
    assert stop.attribution.startswith("© OpenStreetMap") and stop.distance_km < 1 and not stop.is_demo
    places.refresh_nearby(db, college, fetch=lambda lat, lon: parsed[:1])  # replaces, never duplicates
    assert len(db.scalars(select(NearbyPlace).where(NearbyPlace.college_id == cid)).all()) == 1

    demo = db.scalar(select(College).where(College.is_demo.is_(True)))
    with pytest.raises(places.PlacesError):
        places.refresh_nearby(db, demo, fetch=lambda lat, lon: parsed)


def test_readiness_lists_what_blocks_launch(admin):
    body = admin.get("/api/admin/readiness").json()
    items = {i["key"]: i for i in body["items"]}
    assert body["ready"] is False
    assert items["legal_review"]["status"] == "todo" and items["security_config"]["status"] == "todo"
    assert items["demo_data"]["status"] == "warn"
    assert {"eligibility_rules", "info_articles", "source_terms", "ocr", "places", "rate_limit"} <= set(items)


def test_remove_demo_deletes_every_demo_record(tmp_path):
    from sqlalchemy import func
    from sqlalchemy.orm import Session as OrmSession

    from app.db import Base, make_engine
    from app.models import CutoffRecord, EligibilityRule, FeeRecord, User
    from app.seed import remove_demo, seed_demo, seed_demo_accounts, seed_reference

    engine = make_engine(f"sqlite:///{(tmp_path / 'demo.db').as_posix()}")
    Base.metadata.create_all(engine)
    with OrmSession(engine) as s:
        seed_reference(s)
        seed_demo(s)
        seed_demo_accounts(s)
        assert s.scalar(select(func.count()).select_from(CutoffRecord)) > 0
        remove_demo(s)
        for model in (College, CutoffRecord, FeeRecord, NearbyPlace, EligibilityRule, User):
            assert s.scalar(select(func.count()).select_from(model)) == 0, model.__name__
        assert s.scalar(select(func.count()).select_from(InfoArticle)) > 0  # reference data stays
    engine.dispose()
