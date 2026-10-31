"""Admin & data-quality API. Every mutating action writes an AuditLog row."""
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import DEV_JWT_SECRET, get_settings
from app.db import get_db
from app.models import (
    AuditLog, College, CollegeAlias, CounsellingAuthority, CutoffRecord, DataImportJob, DataQualityIssue,
    DataSource, DocumentChunk, EligibilityRule, FeeRecord, HostelRecord, InfoArticle, Question, QuestionReport, SeatMatrix,
    SourceDocument, StudentReview, User, VerificationStatus,
)
from app.security import require_admin
from app.services import places
from app.services.embeddings import embeddings_enabled
from app.services.ingestion import (
    IMPORTERS, ImportRefused, backfill_embeddings, import_questions, ingest_document, resolve_source,
    retry_ocr,
)
from app.services.normalize import normalize_name
from app.services.ocr import ocr_available

router = APIRouter(prefix="/api/admin", tags=["admin"])
MAX_UPLOAD = 20 * 1024 * 1024
VERIFIABLE = {"cutoff_record": CutoffRecord, "fee_record": FeeRecord, "hostel_record": HostelRecord,
              "college": College, "seat_matrix": SeatMatrix, "eligibility_rule": EligibilityRule,
              "info_article": InfoArticle}
KNOWN_RULES = {
    "open_category_accessible": "Reserved-category candidates may also be allotted OPEN seats (true/false).",
    "state_quota_rank_basis": "Which rank the state quota uses: AIR or STATE_RANK.",
}


def audit(db: Session, actor: User, action: str, entity_type: str, entity_id: int | None, changes: dict):
    db.add(AuditLog(actor_id=actor.id, action=action, entity_type=entity_type, entity_id=entity_id,
                    changes={k: str(v) for k, v in changes.items()}))


async def _read(upload: UploadFile, allowed: tuple[str, ...]) -> bytes:
    name = (upload.filename or "").lower()
    if not name.endswith(allowed):
        raise HTTPException(415, f"Allowed file types: {', '.join(allowed)}")
    content = await upload.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, "File too large (max 20 MB).")
    return content


def _count(db: Session, model, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


@router.get("/stats")
def stats(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {
        "colleges": _count(db, College), "demo_colleges": _count(db, College, College.is_demo.is_(True)),
        "cutoff_records": _count(db, CutoffRecord),
        "cutoffs_by_status": dict(db.execute(select(CutoffRecord.verification_status, func.count())
                                             .group_by(CutoffRecord.verification_status)).all()),
        "open_issues": _count(db, DataQualityIssue, DataQualityIssue.status == "open"),
        "pending_reviews": _count(db, StudentReview, StudentReview.status == "pending"),
        "documents": _count(db, SourceDocument),
    }


# ---------------------------------------------------------------- go-live readiness

@router.get("/readiness")
def readiness(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Checklist of what still blocks real use. Computed from the data and configuration."""
    s = get_settings()
    items = []

    def add(key, label, ok, detail, warn=False):
        items.append({"key": key, "label": label, "status": "ok" if ok else ("warn" if warn else "todo"),
                      "detail": detail})

    real_colleges = _count(db, College, College.is_demo.is_(False))
    add("real_colleges", "Real colleges added", real_colleges > 0, f"{real_colleges} non-demo college(s).")
    verified = _count(db, CutoffRecord, CutoffRecord.verification_status == VerificationStatus.verified)
    unverified = _count(db, CutoffRecord, CutoffRecord.verification_status.in_(
        [VerificationStatus.unverified, VerificationStatus.pending_review, VerificationStatus.conflicting]))
    add("verified_cutoffs", "Cutoffs imported and verified", verified > 0 and unverified == 0,
        f"{verified} verified, {unverified} awaiting review or conflicting.")
    for kind, model in (("seat_matrix", SeatMatrix), ("fees", FeeRecord)):
        n = _count(db, model, model.verification_status == VerificationStatus.verified)
        add(f"verified_{kind}", f"{kind.replace('_', ' ').capitalize()} imported and verified", n > 0, f"{n} verified.")

    gaps = eligibility_gaps(db)
    real_cutoffs = db.scalar(select(func.count()).select_from(CutoffRecord).join(College)
                             .where(College.is_demo.is_(False))) or 0
    add("eligibility_rules", "Reserved-category OPEN-seat rule entered per authority and year",
        real_cutoffs > 0 and not gaps,
        "No real cutoffs yet, so there is nothing to cover." if not real_cutoffs else
        "All real authority/year/quota combinations have a verified rule." if not gaps else
        f"{len(gaps)} missing: " + ", ".join(f"{g['authority']} {g['exam_year']} {g['quota']}" for g in gaps[:6])
        + ("…" if len(gaps) > 6 else ""))

    pending_info = _count(db, InfoArticle, InfoArticle.verification_status != VerificationStatus.verified)
    add("info_articles", "NEET info pages checked against the current NTA bulletin", pending_info == 0,
        f"{pending_info} page(s) not yet verified.")
    reviewed_q = dict(db.execute(select(Question.subject, func.count()).where(Question.review_status == "reviewed")
                                 .group_by(Question.subject)).all())
    short = [f"{s}: {reviewed_q.get(s, 0)}" for s in ("Physics", "Chemistry", "Botany", "Zoology") if reviewed_q.get(s, 0) < 45]
    add("question_bank", "Expert-reviewed question bank (enough for a full 180-question mock)", not short,
        "OK." if not short else "Reviewed questions per section (45 needed): " + ", ".join(short)
        + ". Until then students practise on the labelled sample questions.")
    unreviewed = db.scalars(select(DataSource.code).where(DataSource.kind != "demo",
                                                          DataSource.usage_status == "unreviewed")).all()
    add("source_terms", "Terms of use reviewed for every data source", not unreviewed,
        "All reviewed." if not unreviewed else "Not reviewed: " + ", ".join(unreviewed))
    demo = _count(db, College, College.is_demo.is_(True))
    add("demo_data", "Demo data removed (or clearly kept for a sandbox)", demo == 0,
        f"{demo} demo college(s) present. Production databases should be seeded with --no-demo.", warn=True)
    ocr_issues = _count(db, DataQualityIssue, DataQualityIssue.issue_type == "needs_ocr",
                        DataQualityIssue.status == "open")
    add("ocr", "OCR available for scanned PDFs", ocr_available(),
        ("Tesseract found." if ocr_available() else "Tesseract not installed (the Docker image includes it).")
        + (f" {ocr_issues} document(s) waiting for OCR." if ocr_issues else ""), warn=True)
    add("semantic_search", "Semantic search (embeddings) configured", embeddings_enabled(),
        "Voyage embeddings on." if embeddings_enabled() else "VOYAGE_API_KEY not set; keyword (BM25) search only.",
        warn=True)
    add("places", "Maps/places provider connected", s.places_provider != "none",
        f"Provider: {s.places_provider}.", warn=True)
    add("rate_limit", "Shared rate limiting (Redis)", bool(s.redis_url),
        "REDIS_URL set." if s.redis_url else "Per-process limits only; set REDIS_URL when running >1 worker.")
    add("email", "Email delivery for guardian consent", s.email_backend == "smtp",
        f"EMAIL_BACKEND={s.email_backend}.")
    secure = s.jwt_secret != DEV_JWT_SECRET and s.cookie_secure and not s.database_url.startswith("sqlite")
    add("security_config", "Production secrets, HTTPS cookies and PostgreSQL", secure,
        "OK." if secure else "Development defaults in use (JWT secret, COOKIE_SECURE, SQLite).")
    add("legal_review", "DPDP Act 2023 legal review completed", bool(s.dpdp_review_reference),
        f"Reference: {s.dpdp_review_reference}" if s.dpdp_review_reference else
        "Not recorded. Set DPDP_REVIEW_REFERENCE once counsel signs off (see docs/DPDP_READINESS.md).")
    return {"ready": all(i["status"] != "todo" for i in items), "items": items}


def eligibility_gaps(db: Session) -> list[dict]:
    """Real (non-demo) authority/year/quota combinations that have no verified OPEN-seat rule."""
    combos = db.execute(select(CounsellingAuthority.code, CutoffRecord.authority_id, CutoffRecord.exam_year,
                               CutoffRecord.quota).join(CounsellingAuthority).join(College)
                        .where(College.is_demo.is_(False)).distinct()).all()
    gaps = []
    for code, aid, year, quota in combos:
        ok = db.scalar(select(EligibilityRule.id).where(
            EligibilityRule.authority_id == aid, EligibilityRule.exam_year == year,
            EligibilityRule.rule_key == "open_category_accessible", EligibilityRule.quota.in_([quota, "*"]),
            EligibilityRule.verification_status == VerificationStatus.verified))
        if not ok:
            gaps.append({"authority": code, "authority_id": aid, "exam_year": year, "quota": quota})
    return sorted(gaps, key=lambda g: (g["authority"], -g["exam_year"], g["quota"]))


# ---------------------------------------------------------------- data sources & terms of use

def _source_out(d: DataSource) -> dict:
    return {"id": d.id, "code": d.code, "name": d.name, "kind": d.kind, "base_url": d.base_url,
            "terms_url": d.terms_url, "terms_note": d.terms_note, "attribution_text": d.attribution_text,
            "usage_status": d.usage_status, "automated_access_permitted": d.automated_access_permitted,
            "terms_reviewed_at": d.terms_reviewed_at}


@router.get("/data-sources")
def data_sources(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [_source_out(d) for d in db.scalars(select(DataSource).order_by(DataSource.code))]


class SourceIn(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=3, max_length=200)
    kind: Literal["official_portal", "college_site", "licensed_api", "other"]
    base_url: str | None = None


@router.post("/data-sources", status_code=201)
def create_source(body: SourceIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    code = body.code.upper()
    if db.scalar(select(DataSource).where(DataSource.code == code)):
        raise HTTPException(409, "A source with this code already exists.")
    d = DataSource(code=code, name=body.name, kind=body.kind, base_url=body.base_url, usage_status="unreviewed")
    db.add(d)
    db.flush()
    audit(db, admin, "create_data_source", "data_source", d.id, {"code": code})
    db.commit()
    return _source_out(d)


class TermsReviewIn(BaseModel):
    usage_status: Literal["allowed", "restricted", "prohibited", "unreviewed"]
    terms_url: str | None = None
    terms_note: str = Field(min_length=10, max_length=4000)
    attribution_text: str | None = None
    automated_access_permitted: bool = False


@router.patch("/data-sources/{sid}/terms")
def review_terms(sid: int, body: TermsReviewIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    d = db.get(DataSource, sid)
    if d is None:
        raise HTTPException(404, "Not found")
    if d.kind == "demo" and body.usage_status != "allowed":
        raise HTTPException(422, "The demo source is synthetic data; its status stays 'allowed'.")
    audit(db, admin, "review_source_terms", "data_source", sid, {"from": d.usage_status, "to": body.usage_status,
                                                                  "note": body.terms_note})
    d.usage_status, d.terms_url, d.terms_note = body.usage_status, body.terms_url, body.terms_note
    d.attribution_text, d.automated_access_permitted = body.attribution_text, body.automated_access_permitted
    d.terms_reviewed_at, d.terms_reviewed_by = datetime.now(timezone.utc), admin.id
    db.commit()
    return _source_out(d)


# ---------------------------------------------------------------- imports

@router.post("/imports/{kind}")
async def upload_table(kind: Literal["cutoffs", "seat_matrix", "fees"], file: UploadFile = File(...),
                       data_source_code: str = Form(...), source_name: str = Form(..., min_length=3),
                       source_url: str | None = Form(None), publication_date: date | None = Form(None),
                       admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    content = await _read(file, (".csv", ".xlsx"))
    try:
        src = resolve_source(db, data_source_code)
    except ImportRefused as e:
        raise HTTPException(422, str(e))
    job = IMPORTERS[kind](db, content, file.filename, source_name=source_name, source_url=source_url,
                          publication_date=publication_date, data_source=src, user_id=admin.id)
    audit(db, admin, f"import_{kind}", "data_import_job", job.id,
          {"file": file.filename, "status": job.status, "source": src.code if src else None})
    db.commit()
    return _job(job)


@router.post("/questions/import")
async def upload_questions(file: UploadFile = File(...), data_source_code: str = Form(...),
                           source_name: str = Form(..., min_length=3), expert_reviewed: bool = Form(False),
                           admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Question banks are usually copyrighted: the source's terms must allow use (Sources tab)."""
    content = await _read(file, (".csv", ".xlsx"))
    try:
        src = resolve_source(db, data_source_code)
        job = import_questions(db, content, file.filename, source_name=source_name, data_source=src,
                               review_status="reviewed" if expert_reviewed else "draft", user_id=admin.id)
    except ImportRefused as e:
        raise HTTPException(422, str(e))
    audit(db, admin, "import_questions", "data_import_job", job.id,
          {"file": file.filename, "status": job.status, "expert_reviewed": expert_reviewed})
    db.commit()
    return _job(job)


@router.get("/questions/summary")
def question_summary(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.execute(select(Question.subject, Question.review_status, func.count())
                      .group_by(Question.subject, Question.review_status)).all()
    out: dict[str, dict[str, int]] = {}
    for subject, status, n in rows:
        out.setdefault(subject, {})[status] = n
    return out


@router.get("/questions/reports")
def question_reports(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Questions students reported, most-reported first, with the reasons and notes."""
    reports = db.scalars(select(QuestionReport).where(QuestionReport.status == "open")
                         .order_by(QuestionReport.id.desc()).limit(500)).all()
    by_q: dict[int, list] = {}
    for r in reports:
        by_q.setdefault(r.question_id, []).append({"reason": r.reason, "note": r.note, "created_at": r.created_at})
    out = []
    for qid, items in by_q.items():
        q = db.get(Question, qid)
        out.append({"id": q.id, "subject": q.subject, "chapter": q.chapter.name, "stem": q.stem, "options": q.options,
                    "correct_index": q.correct_index, "explanation": q.explanation, "review_status": q.review_status,
                    "generated_by": q.generated_by, "checked_by": q.checked_by, "reports": items})
    return sorted(out, key=lambda q: -len(q["reports"]))


class QuestionStatusIn(BaseModel):
    review_status: Literal["draft", "sample", "ai_checked", "reviewed", "retired"]


@router.patch("/questions/{qid}")
def set_question_status(qid: int, body: QuestionStatusIn, admin: User = Depends(require_admin),
                        db: Session = Depends(get_db)):
    q = db.get(Question, qid)
    if q is None:
        raise HTTPException(404, "Not found")
    audit(db, admin, "set_question_status", "question", qid, {"from": q.review_status, "to": body.review_status})
    q.review_status = body.review_status
    # Deciding on a reported question closes its reports: retired = the report was right; restored = dismissed.
    for r in db.scalars(select(QuestionReport).where(QuestionReport.question_id == qid, QuestionReport.status == "open")):
        r.status = "fixed" if body.review_status in ("retired", "draft") else "dismissed"
    if body.review_status in ("ai_checked", "reviewed"):
        q.report_count = 0
    db.commit()
    return {"ok": True}


@router.post("/documents")
async def upload_document(file: UploadFile = File(...), title: str = Form(...), url: str | None = Form(None),
                          authority: str | None = Form(None), doc_type: str = Form("notice"),
                          exam_year: int | None = Form(None), state: str | None = Form(None),
                          publication_date: date | None = Form(None),
                          admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    content = await _read(file, (".pdf", ".txt", ".md"))
    try:
        doc = ingest_document(db, content, file.filename, title=title, url=url, authority=authority,
                              doc_type=doc_type, exam_year=exam_year, state=state,
                              publication_date=publication_date, user_id=admin.id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    audit(db, admin, "upload_document", "source_document", doc.id, {"title": title})
    db.commit()
    return {"id": doc.id, "title": doc.title, "version": doc.version, "chunks": len(doc.chunks)}


@router.get("/documents")
def documents(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.execute(select(SourceDocument, func.count(DocumentChunk.id),
                             func.count(DocumentChunk.embedding))
                      .outerjoin(DocumentChunk).group_by(SourceDocument.id)
                      .order_by(SourceDocument.id.desc()).limit(200)).all()
    needs_ocr = set(db.scalars(select(DataQualityIssue.entity_id).where(
        DataQualityIssue.issue_type == "needs_ocr", DataQualityIssue.status == "open")))
    return [{"id": d.id, "title": d.title, "doc_type": d.doc_type, "authority": d.authority,
             "exam_year": d.exam_year, "version": d.version, "url": d.url, "chunks": n, "embedded": e,
             "needs_ocr": d.id in needs_ocr, "verification_status": d.verification_status.value,
             "created_at": d.created_at} for d, n, e in rows]


@router.post("/documents/{did}/ocr")
def ocr_document(did: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    doc = db.get(SourceDocument, did)
    if doc is None:
        raise HTTPException(404, "Not found")
    try:
        job = retry_ocr(db, doc, admin.id)
    except ImportRefused as e:
        raise HTTPException(422, str(e))
    audit(db, admin, "ocr_document", "source_document", did, {"status": job.status})
    db.commit()
    return _job(job)


@router.post("/embeddings/backfill")
def embeddings_backfill(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not embeddings_enabled():
        raise HTTPException(422, "Semantic search is not configured (set VOYAGE_API_KEY).")
    n = backfill_embeddings(db)
    audit(db, admin, "backfill_embeddings", "document_chunk", None, {"embedded": n})
    db.commit()
    return {"embedded": n}


def _job(j: DataImportJob) -> dict:
    return {"id": j.id, "kind": j.kind, "status": j.status, "filename": j.filename, "started_at": j.started_at,
            "finished_at": j.finished_at, "rows_read": j.rows_read, "inserted": j.inserted, "updated": j.updated,
            "skipped": j.skipped, "errors": (j.errors or [])[:50], "data_version": j.data_version}


@router.get("/imports")
def jobs(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [_job(j) for j in db.scalars(select(DataImportJob).order_by(DataImportJob.id.desc()).limit(100))]


# ---------------------------------------------------------------- issues & verification

@router.get("/issues")
def issues(status: str = "open", _: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(DataQualityIssue).where(DataQualityIssue.status == status)
                      .order_by(DataQualityIssue.id.desc()).limit(200)).all()
    return [{"id": i.id, "entity_type": i.entity_type, "entity_id": i.entity_id, "issue_type": i.issue_type,
             "details": i.details, "status": i.status, "import_job_id": i.import_job_id, "created_at": i.created_at}
            for i in rows]


class IssuePatch(BaseModel):
    status: str = Field(pattern="^(resolved|ignored|open)$")
    note: str | None = None


@router.patch("/issues/{iid}")
def patch_issue(iid: int, body: IssuePatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    i = db.get(DataQualityIssue, iid)
    if i is None:
        raise HTTPException(404, "Not found")
    audit(db, admin, "update_issue", "data_quality_issue", iid, {"from": i.status, "to": body.status, "note": body.note})
    i.status = body.status
    db.commit()
    return {"ok": True}


class VerifyIn(BaseModel):
    entity_type: str
    entity_id: int
    status: VerificationStatus


@router.post("/verify")
def verify(body: VerifyIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    model = VERIFIABLE.get(body.entity_type)
    if model is None:
        raise HTTPException(422, f"entity_type must be one of {', '.join(VERIFIABLE)}")
    rec = db.get(model, body.entity_id)
    if rec is None:
        raise HTTPException(404, "Record not found")
    if body.status == VerificationStatus.verified:
        if getattr(rec, "is_demo", False) or rec.verification_status == VerificationStatus.demo:
            raise HTTPException(422, "Demo records can never be marked verified.")
        if not (rec.source_url or rec.source_document_id):
            raise HTTPException(422, "Add the official source (URL or uploaded document) before verifying.")
        if isinstance(rec, InfoArticle) and not rec.exam_year:
            raise HTTPException(422, "Set the exam year this page was checked against before verifying.")
    if body.status == VerificationStatus.demo:
        raise HTTPException(422, "Records cannot be switched to demo status.")
    audit(db, admin, "set_verification", body.entity_type, rec.id,
          {"from": rec.verification_status.value, "to": body.status.value})
    rec.verification_status = body.status
    if body.status == VerificationStatus.verified:
        rec.last_verified_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- eligibility rules

def _rule_out(r: EligibilityRule, codes: dict[int, str]) -> dict:
    return {"id": r.id, "authority": codes.get(r.authority_id), "authority_id": r.authority_id,
            "exam_year": r.exam_year, "quota": r.quota, "rule_key": r.rule_key, "value": r.rule_value.get("value"),
            "description": r.description, "source_name": r.source_name, "source_url": r.source_url,
            "publication_date": r.publication_date, "verification_status": r.verification_status.value,
            "last_verified_at": r.last_verified_at}


@router.get("/eligibility-rules")
def eligibility_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    codes = dict(db.execute(select(CounsellingAuthority.id, CounsellingAuthority.code)).all())
    rules = db.scalars(select(EligibilityRule).where(EligibilityRule.verification_status != VerificationStatus.demo)
                       .order_by(EligibilityRule.authority_id, EligibilityRule.exam_year.desc())).all()
    return {"known_rules": KNOWN_RULES, "rules": [_rule_out(r, codes) for r in rules], "gaps": eligibility_gaps(db),
            "authorities": [{"id": a.id, "code": a.code, "quotas": a.quotas}
                            for a in db.scalars(select(CounsellingAuthority).order_by(CounsellingAuthority.code))]}


class RuleIn(BaseModel):
    authority_id: int
    exam_year: int = Field(ge=2000, le=2100)
    quota: str = Field(min_length=1, max_length=30)
    rule_key: Literal["open_category_accessible", "state_quota_rank_basis"]
    value: bool | str
    description: str | None = None
    source_name: str = Field(min_length=3, max_length=200)
    source_url: str = Field(min_length=8, max_length=500)
    publication_date: date | None = None


@router.put("/eligibility-rules")
def upsert_rule(body: RuleIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    auth = db.get(CounsellingAuthority, body.authority_id)
    if auth is None:
        raise HTTPException(404, "Authority not found")
    if body.quota != "*" and body.quota not in (auth.quotas or []):
        raise HTTPException(422, f"{auth.code} does not run quota {body.quota}")
    if body.rule_key == "open_category_accessible" and not isinstance(body.value, bool):
        raise HTTPException(422, "open_category_accessible must be true or false")
    if body.rule_key == "state_quota_rank_basis" and body.value not in ("AIR", "STATE_RANK"):
        raise HTTPException(422, "state_quota_rank_basis must be AIR or STATE_RANK")
    rule = db.scalar(select(EligibilityRule).where(
        EligibilityRule.authority_id == body.authority_id, EligibilityRule.exam_year == body.exam_year,
        EligibilityRule.quota == body.quota, EligibilityRule.rule_key == body.rule_key))
    if rule is not None and rule.verification_status == VerificationStatus.demo:
        raise HTTPException(409, "A demo rule exists for this key; real rules cannot replace demo rows. "
                                 "Use a database without demo data.")
    before = None if rule is None else rule.rule_value.get("value")
    if rule is None:
        rule = EligibilityRule(authority_id=body.authority_id, exam_year=body.exam_year, quota=body.quota,
                               rule_key=body.rule_key, rule_value={}, source_name=body.source_name)
        db.add(rule)
    rule.rule_value = {"value": body.value}
    rule.description = body.description
    rule.source_name, rule.source_url, rule.publication_date = body.source_name, body.source_url, body.publication_date
    rule.verification_status = VerificationStatus.unverified  # verified separately, after checking the source
    rule.last_verified_at = None
    db.flush()
    audit(db, admin, "upsert_eligibility_rule", "eligibility_rule", rule.id,
          {"key": body.rule_key, "from": before, "to": body.value, "source": body.source_url})
    db.commit()
    return _rule_out(rule, {auth.id: auth.code})


# ---------------------------------------------------------------- info hub review

def _article_out(a: InfoArticle) -> dict:
    return {"id": a.id, "section": a.section, "slug": a.slug, "title": a.title, "body": a.body,
            "exam_year": a.exam_year, "source_name": a.source_name, "source_url": a.source_url,
            "source_document_id": a.source_document_id, "publication_date": a.publication_date,
            "verification_status": a.verification_status.value, "last_verified_at": a.last_verified_at}


@router.get("/info-articles")
def info_articles(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [_article_out(a) for a in db.scalars(select(InfoArticle).order_by(InfoArticle.section, InfoArticle.sort_order))]


class ArticlePatch(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=200)
    body: str | None = Field(None, min_length=20)
    exam_year: int | None = Field(None, ge=2000, le=2100)
    source_name: str | None = Field(None, min_length=3)
    source_url: str | None = None
    source_document_id: int | None = None
    publication_date: date | None = None


@router.patch("/info-articles/{aid}")
def edit_article(aid: int, body: ArticlePatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    a = db.get(InfoArticle, aid)
    if a is None:
        raise HTTPException(404, "Not found")
    changes = body.model_dump(exclude_unset=True)
    if "source_document_id" in changes and changes["source_document_id"] is not None \
            and db.get(SourceDocument, changes["source_document_id"]) is None:
        raise HTTPException(422, "Unknown source document")
    for k, v in changes.items():
        setattr(a, k, v)
    a.verification_status = VerificationStatus.pending_review  # any edit needs a fresh check
    a.last_verified_at = None
    audit(db, admin, "edit_info_article", "info_article", aid, {k: str(v)[:200] for k, v in changes.items()})
    db.commit()
    return _article_out(a)


# ---------------------------------------------------------------- colleges, aliases, nearby

class CollegeIn(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=3, max_length=250)
    state: str
    city: str | None = None
    address: str | None = None
    institution_type: str
    website: str | None = None
    established_year: int | None = None
    latitude: float | None = Field(None, ge=6, le=38)    # India's bounding box
    longitude: float | None = Field(None, ge=68, le=98)
    recognition_status: str | None = None
    recognition_year: str | None = None
    aliases: list[str] = []
    source_name: str = Field(min_length=3)
    source_url: str | None = None


@router.post("/colleges", status_code=201)
def create_college(body: CollegeIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(College).where(College.code == body.code)):
        raise HTTPException(409, "A college with this code already exists.")
    c = College(**body.model_dump(exclude={"aliases"}), verification_status=VerificationStatus.unverified)
    c.aliases = [CollegeAlias(alias=a, normalized=normalize_name(a)) for a in body.aliases]
    db.add(c)
    db.flush()
    audit(db, admin, "create_college", "college", c.id, {"code": c.code})
    db.commit()
    return {"id": c.id}


class CollegePatch(BaseModel):
    city: str | None = None
    address: str | None = None
    website: str | None = None
    latitude: float | None = Field(None, ge=6, le=38)
    longitude: float | None = Field(None, ge=68, le=98)
    recognition_status: str | None = None
    recognition_year: str | None = None
    source_name: str | None = Field(None, min_length=3)
    source_url: str | None = None


@router.patch("/colleges/{cid}")
def patch_college(cid: int, body: CollegePatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(College, cid)
    if c is None:
        raise HTTPException(404, "College not found")
    if c.is_demo:
        raise HTTPException(422, "Demo colleges are fictional and cannot be edited into real records.")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(c, k, v)
    c.verification_status = VerificationStatus.unverified
    audit(db, admin, "edit_college", "college", cid, changes)
    db.commit()
    return {"ok": True}


@router.post("/colleges/{cid}/nearby/refresh")
def refresh_nearby(cid: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(College, cid)
    if c is None:
        raise HTTPException(404, "College not found")
    try:
        rows = places.refresh_nearby(db, c)
    except places.PlacesError as e:
        raise HTTPException(422, str(e))
    audit(db, admin, "refresh_nearby", "college", cid, {"places": len(rows)})
    db.commit()
    return {"places": len(rows)}


@router.post("/colleges/{cid}/aliases", status_code=201)
def add_alias(cid: int, alias: str = Form(...), admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(College, cid)
    if c is None:
        raise HTTPException(404, "College not found")
    key = normalize_name(alias)
    if db.scalar(select(CollegeAlias).where(CollegeAlias.normalized == key)):
        raise HTTPException(409, "Alias already mapped (possible duplicate college) — resolve manually.")
    db.add(CollegeAlias(college_id=cid, alias=alias, normalized=key))
    audit(db, admin, "add_alias", "college", cid, {"alias": alias})
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- reviews & audit

@router.get("/reviews")
def pending_reviews(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(StudentReview).where(StudentReview.status == "pending").limit(100)).all()
    return [{"id": r.id, "college_id": r.college_id, "rating": r.rating, "body": r.body,
             "aspect_ratings": r.aspect_ratings, "created_at": r.created_at} for r in rows]


class ModerateIn(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")
    note: str | None = None


@router.patch("/reviews/{rid}")
def moderate(rid: int, body: ModerateIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(StudentReview, rid)
    if r is None:
        raise HTTPException(404, "Not found")
    r.status, r.moderation_note = body.status, body.note
    audit(db, admin, "moderate_review", "student_review", rid, {"status": body.status})
    db.commit()
    return {"ok": True}


@router.get("/audit")
def audit_log(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200)).all()
    return [{"id": a.id, "actor_id": a.actor_id, "action": a.action, "entity_type": a.entity_type,
             "entity_id": a.entity_id, "changes": a.changes, "created_at": a.created_at} for a in rows]
