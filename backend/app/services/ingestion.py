"""ETL for official datasets: raw file storage → parse → normalise → validate → upsert.

Guarantees (cutoffs, seat matrices and fees alike)
- Raw files are stored by SHA-256 with a SourceDocument row (provenance).
- Re-importing identical content is a no-op (idempotent); unchanged rows are skipped.
- Rows are never auto-created for unknown colleges: a DataQualityIssue is raised instead.
- A changed value on a *verified* record is not overwritten — it is flagged as a conflict.
- Rows attached to a demo college are always stored with status "demo".
- Every run is logged as a DataImportJob with counts and row-level errors.
- When a registered data source is named, its terms-of-use review must say usage is allowed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    College, CollegeAlias, CounsellingAuthority, Course, CutoffRecord, DataImportJob, DataQualityIssue,
    DataSource, DocumentChunk, FeeRecord, RankBasis, SeatMatrix, SourceDocument, VerificationStatus,
)
from app.services.normalize import (
    normalize_category, normalize_course, normalize_name, normalize_quota, normalize_seat_type,
)

CUTOFF_COLUMNS = [
    "college_code", "college_name", "course", "authority", "exam_year", "round", "round_name", "quota",
    "category", "seat_type", "domicile_required", "rank_basis", "opening_rank", "closing_rank",
]
SEAT_MATRIX_COLUMNS = ["college_code", "college_name", "course", "authority", "exam_year", "round", "quota",
                       "category", "seat_type", "seats"]
FEE_COLUMNS = ["college_code", "college_name", "course", "academic_year", "quota", "fee_type", "amount_inr",
               "period", "mandatory", "refundable", "note"]
FEE_TYPES = {"tuition", "admission", "exam", "security_deposit", "hostel", "mess", "other"}
FEE_PERIODS = {"annual", "one_time", "monthly", "course"}


class ImportRefused(ValueError):
    """The import cannot start (e.g. the named source's terms of use do not allow it)."""


class RowError(ValueError):
    def __init__(self, msg: str, issue: str = "invalid_row"):
        super().__init__(msg)
        self.issue = issue


def store_raw(content: bytes, filename: str) -> tuple[str, Path]:
    sha = hashlib.sha256(content).hexdigest()
    ext = Path(filename).suffix.lower() or ".bin"
    raw_dir = get_settings().storage_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{sha}{ext}"
    if not path.exists():
        path.write_bytes(content)
    return sha, path


def read_table(content: bytes, filename: str) -> list[dict]:
    name = filename.lower()
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig")
        return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(io.StringIO(text))]
    if name.endswith(".xlsx"):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        rows = list(wb.active.iter_rows(values_only=True))
        if not rows:
            return []
        header = [str(h or "").strip().lower() for h in rows[0]]
        return [{header[i]: ("" if v is None else str(v).strip()) for i, v in enumerate(r) if i < len(header)}
                for r in rows[1:] if any(v not in (None, "") for v in r)]
    raise ValueError("Unsupported file type. Upload CSV or XLSX (PDF tables: extract to CSV first).")


def resolve_college(db: Session, code: str | None, name: str | None) -> College | None:
    if code:
        c = db.scalar(select(College).where(College.code == code))
        if c:
            return c
    if name:
        key = normalize_name(name)
        alias = db.scalar(select(CollegeAlias).where(CollegeAlias.normalized == key))
        if alias:
            return db.get(College, alias.college_id)
        for c in db.scalars(select(College)):
            if normalize_name(c.name) == key:
                return c
    return None


def resolve_source(db: Session, code: str | None) -> DataSource | None:
    """Look up a registered data source and enforce its terms-of-use review."""
    if not code:
        return None
    src = db.scalar(select(DataSource).where(DataSource.code == code.strip().upper()))
    if src is None:
        raise ImportRefused(f"Unknown data source '{code}'. Register it and review its terms of use first.")
    if src.usage_status != "allowed":
        raise ImportRefused(f"Data source {src.code} has terms-of-use status '{src.usage_status}'. "
                            "An admin must review its terms and mark usage as allowed before importing.")
    return src


def _int(v: str | None) -> int | None:
    if v in (None, ""):
        return None
    return int(float(str(v).replace(",", "").replace("₹", "").strip()))


def _bool(v: str | None, default: bool = False) -> bool:
    if v in (None, ""):
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


# ---------------------------------------------------------------- generic runner

class _Ctx:
    """Lookups shared by all table importers."""

    def __init__(self, db: Session):
        self.db = db
        self.authorities = {a.code: a for a in db.scalars(select(CounsellingAuthority))}
        self.courses = {c.code: c for c in db.scalars(select(Course))}

    def college(self, row: dict) -> College:
        c = resolve_college(self.db, row.get("college_code"), row.get("college_name"))
        if c is None:
            raise RowError(f"Unknown college '{row.get('college_code') or row.get('college_name')}' — "
                           "add it or an alias first", "unknown_college")
        return c

    def course(self, raw: str | None, required: bool = True) -> Course | None:
        if not raw:
            if required:
                raise RowError("Missing course")
            return None
        c = self.courses.get(normalize_course(raw) or "")
        if c is None:
            raise RowError(f"Unrecognised course '{raw}'")
        return c

    def authority(self, raw: str) -> CounsellingAuthority:
        a = self.authorities.get(raw.strip().upper())
        if a is None:
            raise RowError(f"Unrecognised authority '{raw}'")
        return a


def _norm(fn: Callable[[str | None], str | None], label: str, raw: str | None) -> str:
    v = fn(raw)
    if v is None:
        raise RowError(f"Unrecognised {label} '{raw}'")
    return v


def _year(v: str) -> int:
    y = _int(v)
    if y is None or not (2000 <= y <= date.today().year + 1):
        raise RowError(f"Implausible exam_year {v}")
    return y


def _run_import(db: Session, content: bytes, filename: str, *, kind: str, entity_type: str, model,
                required: set[str], parse_row: Callable[[_Ctx, dict], tuple[College, dict, dict]],
                source_name: str, source_url: str | None, publication_date: date | None,
                verification_status: VerificationStatus, data_source: DataSource | None,
                user_id: int | None) -> DataImportJob:
    sha, path = store_raw(content, filename)
    doc = db.scalar(select(SourceDocument).where(SourceDocument.sha256 == sha))
    if doc is None:
        doc = SourceDocument(title=filename, url=source_url, doc_type=kind, sha256=sha, stored_path=str(path),
                             publication_date=publication_date, last_checked_at=datetime.now(timezone.utc),
                             verification_status=verification_status,
                             data_source_id=data_source.id if data_source else None)
        db.add(doc)
        db.flush()

    job = DataImportJob(kind=kind, filename=filename, source_document_id=doc.id, data_version=sha[:12],
                        triggered_by=user_id)
    db.add(job)
    db.flush()

    try:
        rows = read_table(content, filename)
    except Exception as exc:  # parsing failure: log and keep previously verified data untouched
        job.status, job.finished_at = "failed", datetime.now(timezone.utc)
        job.errors = [{"row": None, "error": f"Could not parse file: {exc}"}]
        db.commit()
        return job

    ctx = _Ctx(db)
    errors: list[dict] = []
    for i, row in enumerate(rows, start=2):  # row 1 is the header
        job.rows_read += 1
        try:
            missing = [c for c in required if not row.get(c)]
            if missing:
                raise RowError(f"Missing required column(s): {', '.join(sorted(missing))}")
            if not (row.get("college_code") or row.get("college_name")):
                raise RowError("Missing college_code or college_name")
            college, natural, values = parse_row(ctx, row)
        except RowError as e:
            errors.append({"row": i, "error": str(e)})
            db.add(DataQualityIssue(entity_type=entity_type, issue_type=e.issue,
                                    details={"row": i, "error": str(e), "data": row}, import_job_id=job.id))
            job.skipped += 1
            continue

        # Data attached to a demo college can never look real.
        row_status = VerificationStatus.demo if college.is_demo else verification_status
        existing = db.scalar(select(model).filter_by(**natural))
        if existing is None:
            db.add(model(**natural, **values, source_name=source_name, source_url=source_url,
                         publication_date=publication_date, verification_status=row_status,
                         source_document_id=doc.id, import_job_id=job.id))
            db.flush()
            job.inserted += 1
            continue
        changed = {k: (getattr(existing, k), v) for k, v in values.items()
                   if v is not None and getattr(existing, k) != v}
        if not changed:
            job.skipped += 1
            continue
        if existing.verification_status == VerificationStatus.verified:
            existing.verification_status = VerificationStatus.conflicting
            db.add(DataQualityIssue(
                entity_type=entity_type, entity_id=existing.id, issue_type="conflict",
                details={"row": i, "changes": {k: [str(a), str(b)] for k, (a, b) in changed.items()},
                         "new_source": source_name},
                import_job_id=job.id))
            errors.append({"row": i, "error": "Conflicts with a verified record — flagged for review"})
            job.skipped += 1
            continue
        for k, (_, v) in changed.items():
            setattr(existing, k, v)
        existing.source_name, existing.source_url = source_name, source_url
        existing.publication_date = publication_date or existing.publication_date
        existing.source_document_id, existing.import_job_id = doc.id, job.id
        existing.verification_status = row_status
        job.updated += 1

    job.errors = errors[:500]
    job.status = "succeeded" if not errors else ("partial" if job.inserted + job.updated else "failed")
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    return job


# ---------------------------------------------------------------- cutoffs

def _cutoff_row(ctx: _Ctx, row: dict):
    college = ctx.college(row)
    course, authority = ctx.course(row["course"]), ctx.authority(row["authority"])
    quota = _norm(normalize_quota, "quota", row["quota"])
    category = _norm(normalize_category, "category", row["category"])
    seat_type = _norm(normalize_seat_type, "seat_type", row.get("seat_type"))
    try:
        rnd = _int(row["round"])
        opening, closing = _int(row.get("opening_rank")), _int(row["closing_rank"])
    except ValueError:
        raise RowError("Year, round and ranks must be numbers")
    year = _year(row["exam_year"])
    basis_raw = (row.get("rank_basis") or "AIR").strip().upper()
    if basis_raw not in RankBasis.__members__:
        raise RowError(f"rank_basis must be AIR or STATE_RANK, got '{basis_raw}'")
    if closing is None or closing <= 0 or (opening is not None and (opening <= 0 or opening > closing)):
        raise RowError("Ranks must be positive and opening_rank ≤ closing_rank")
    if quota not in (authority.quotas or []):
        raise RowError(f"Quota {quota} is not run by {authority.code}")
    natural = dict(college_id=college.id, course_id=course.id, authority_id=authority.id, exam_year=year,
                   round_number=rnd, quota=quota, category=category, seat_type=seat_type)
    values = dict(opening_rank=opening, closing_rank=closing, rank_basis=RankBasis[basis_raw],
                  domicile_required=_bool(row.get("domicile_required")), round_name=row.get("round_name") or None)
    return college, natural, values


def import_cutoffs(db: Session, content: bytes, filename: str, *, source_name: str,
                   source_url: str | None, publication_date: date | None,
                   verification_status: VerificationStatus = VerificationStatus.unverified,
                   data_source: DataSource | None = None, user_id: int | None = None) -> DataImportJob:
    return _run_import(db, content, filename, kind="cutoffs", entity_type="cutoff_record", model=CutoffRecord,
                       required={"course", "authority", "exam_year", "round", "quota", "category", "closing_rank"},
                       parse_row=_cutoff_row, source_name=source_name, source_url=source_url,
                       publication_date=publication_date, verification_status=verification_status,
                       data_source=data_source, user_id=user_id)


# ---------------------------------------------------------------- seat matrix

def _seat_row(ctx: _Ctx, row: dict):
    college = ctx.college(row)
    course, authority = ctx.course(row["course"]), ctx.authority(row["authority"])
    quota = _norm(normalize_quota, "quota", row["quota"])
    category = _norm(normalize_category, "category", row["category"])
    seat_type = _norm(normalize_seat_type, "seat_type", row.get("seat_type"))
    try:
        rnd, seats = _int(row["round"]), _int(row["seats"])
    except ValueError:
        raise RowError("Round and seats must be numbers")
    year = _year(row["exam_year"])
    if seats is None or seats < 0 or seats > 2000:
        raise RowError(f"Implausible seat count {row['seats']}")
    if quota not in (authority.quotas or []):
        raise RowError(f"Quota {quota} is not run by {authority.code}")
    natural = dict(college_id=college.id, course_id=course.id, authority_id=authority.id, exam_year=year,
                   round_number=rnd, quota=quota, category=category, seat_type=seat_type)
    return college, natural, dict(seats=seats)


def import_seat_matrix(db: Session, content: bytes, filename: str, *, source_name: str,
                       source_url: str | None, publication_date: date | None,
                       verification_status: VerificationStatus = VerificationStatus.unverified,
                       data_source: DataSource | None = None, user_id: int | None = None) -> DataImportJob:
    return _run_import(db, content, filename, kind="seat_matrix", entity_type="seat_matrix", model=SeatMatrix,
                       required={"course", "authority", "exam_year", "round", "quota", "category", "seats"},
                       parse_row=_seat_row, source_name=source_name, source_url=source_url,
                       publication_date=publication_date, verification_status=verification_status,
                       data_source=data_source, user_id=user_id)


# ---------------------------------------------------------------- fees

def _fee_row(ctx: _Ctx, row: dict):
    college = ctx.college(row)
    course = ctx.course(row.get("course"), required=False)
    ay = row["academic_year"].strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})", ay)
    if not m or (int(m.group(1)) + 1) % 100 != int(m.group(2)) or not 2000 <= int(m.group(1)) <= date.today().year + 1:
        raise RowError(f"academic_year must look like 2025-26, got '{ay}'")
    quota_raw = (row.get("quota") or "ALL").strip()
    quota = "ALL" if quota_raw.upper() == "ALL" else _norm(normalize_quota, "quota", quota_raw)
    fee_type = row["fee_type"].strip().lower()
    if fee_type not in FEE_TYPES:
        raise RowError(f"fee_type must be one of {', '.join(sorted(FEE_TYPES))}")
    period = row["period"].strip().lower()
    if period not in FEE_PERIODS:
        raise RowError(f"period must be one of {', '.join(sorted(FEE_PERIODS))}")
    try:
        amount = _int(row["amount_inr"])
    except ValueError:
        raise RowError("amount_inr must be a number (rupees, no lakh/crore words)")
    if amount is None or amount < 0 or amount > 50_000_000:
        raise RowError(f"Implausible amount_inr {row['amount_inr']}")
    natural = dict(college_id=college.id, course_id=course.id if course else None, academic_year=ay,
                   quota=quota, fee_type=fee_type)
    values = dict(amount_inr=amount, period=period, mandatory=_bool(row.get("mandatory"), True),
                  refundable=_bool(row.get("refundable"), fee_type == "security_deposit"),
                  note=row.get("note") or None)
    return college, natural, values


def import_fees(db: Session, content: bytes, filename: str, *, source_name: str,
                source_url: str | None, publication_date: date | None,
                verification_status: VerificationStatus = VerificationStatus.unverified,
                data_source: DataSource | None = None, user_id: int | None = None) -> DataImportJob:
    return _run_import(db, content, filename, kind="fees", entity_type="fee_record", model=FeeRecord,
                       required={"academic_year", "fee_type", "amount_inr", "period"},
                       parse_row=_fee_row, source_name=source_name, source_url=source_url,
                       publication_date=publication_date, verification_status=verification_status,
                       data_source=data_source, user_id=user_id)


IMPORTERS = {"cutoffs": import_cutoffs, "seat_matrix": import_seat_matrix, "fees": import_fees}


# ---------------------------------------------------------------- documents (RAG)

def chunk_text(text: str, size: int = 1200) -> list[str]:
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) > size and cur:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def _embed_chunks(chunks: list[DocumentChunk]) -> int:
    from app.services.embeddings import embed
    vectors = embed([c.text for c in chunks], "document")
    if not vectors:
        return 0
    model = get_settings().embedding_model
    for c, v in zip(chunks, vectors):
        c.embedding, c.embedding_model = v, model
    return len(vectors)


def backfill_embeddings(db: Session, limit: int = 2000) -> int:
    """Embed chunks that have no vector yet (e.g. ingested before a key was configured)."""
    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.embedding.is_(None)).limit(limit)).all()
    n = _embed_chunks(list(chunks))
    db.commit()
    return n


def _ocr_pages(db: Session, doc: SourceDocument, content: bytes, pages: list[int], job: DataImportJob) -> int:
    """OCR empty pages and index them. Returns the number of pages still without text."""
    from app.services.ocr import ocr_available, ocr_pdf_pages
    if not pages or not ocr_available():
        return len(pages)
    try:
        texts = ocr_pdf_pages(content, pages)
    except Exception as exc:  # noqa: BLE001 - OCR engine errors must not lose the upload
        job.errors = (job.errors or []) + [{"row": None, "error": f"OCR failed: {exc}"}]
        return len(pages)
    done = 0
    for page, text in texts.items():
        if not text.strip():
            continue
        for chunk in chunk_text(text):
            db.add(DocumentChunk(document_id=doc.id, page=page, text=chunk, extraction="ocr"))
        done += 1
    if done:
        db.add(DataQualityIssue(entity_type="source_document", entity_id=doc.id, issue_type="ocr_text_needs_review",
                                details={"ocr_pages": sorted(texts)}, import_job_id=job.id))
    return len(pages) - done


def ingest_document(db: Session, content: bytes, filename: str, *, title: str, url: str | None,
                    authority: str | None, doc_type: str, exam_year: int | None, state: str | None,
                    publication_date: date | None, user_id: int | None = None) -> SourceDocument:
    """Store an official PDF/TXT document and index its text for retrieval (RAG)."""
    sha, path = store_raw(content, filename)
    existing = db.scalar(select(SourceDocument).where(SourceDocument.sha256 == sha))
    if existing is not None:
        existing.last_checked_at = datetime.now(timezone.utc)
        db.commit()
        return existing

    pages: list[tuple[int | None, str]] = []
    if filename.lower().endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        pages = [(n + 1, (p.extract_text() or "")) for n, p in enumerate(reader.pages)]
    elif filename.lower().endswith((".txt", ".md")):
        pages = [(None, content.decode("utf-8", errors="replace"))]
    else:
        raise ValueError("Upload PDF, TXT or MD documents.")

    # Previous versions of the same titled document are kept; this one gets the next version.
    prev = db.scalars(select(SourceDocument).where(SourceDocument.title == title)).all()
    doc = SourceDocument(title=title, url=url, authority=authority, doc_type=doc_type, exam_year=exam_year,
                         state=state, publication_date=publication_date, sha256=sha, stored_path=str(path),
                         last_checked_at=datetime.now(timezone.utc), version=len(prev) + 1)
    db.add(doc)
    db.flush()
    job = DataImportJob(kind="document", filename=filename, source_document_id=doc.id,
                        data_version=sha[:12], triggered_by=user_id)
    db.add(job)
    db.flush()
    empty: list[int] = []
    for page, text in pages:
        if not text.strip():
            if page is not None:
                empty.append(page)
            continue
        for chunk in chunk_text(text):
            db.add(DocumentChunk(document_id=doc.id, page=page, text=chunk))
    still_empty = _ocr_pages(db, doc, content, empty, job)
    if still_empty:
        job.errors = (job.errors or []) + [
            {"row": None, "error": f"{still_empty} page(s) had no extractable text (scanned?). OCR needed."}]
        db.add(DataQualityIssue(entity_type="source_document", entity_id=doc.id, issue_type="needs_ocr",
                                details={"empty_pages": still_empty}, import_job_id=job.id))
    db.flush()
    _embed_chunks(list(db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id))))
    job.status = "succeeded" if not still_empty else "partial"
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    return doc


def retry_ocr(db: Session, doc: SourceDocument, user_id: int | None = None) -> DataImportJob:
    """Re-run OCR on a stored PDF's pages that have no indexed text (e.g. after installing Tesseract)."""
    from app.services.ocr import ocr_available
    if not ocr_available():
        raise ImportRefused("OCR is not available: install Tesseract (and pypdfium2/pytesseract) and set OCR_ENABLED.")
    if not (doc.stored_path or "").lower().endswith(".pdf"):
        raise ImportRefused("Only PDF documents can be OCR'd.")
    content = Path(doc.stored_path).read_bytes()
    from pypdf import PdfReader
    total = len(PdfReader(io.BytesIO(content)).pages)
    have = {p for (p,) in db.execute(select(DocumentChunk.page).where(DocumentChunk.document_id == doc.id))}
    missing = [n for n in range(1, total + 1) if n not in have]
    job = DataImportJob(kind="ocr", filename=Path(doc.stored_path).name, source_document_id=doc.id,
                        data_version=(doc.sha256 or "")[:12], triggered_by=user_id)
    db.add(job)
    db.flush()
    still_empty = _ocr_pages(db, doc, content, missing, job)
    if not still_empty:
        for issue in db.scalars(select(DataQualityIssue).where(
                DataQualityIssue.entity_type == "source_document", DataQualityIssue.entity_id == doc.id,
                DataQualityIssue.issue_type == "needs_ocr", DataQualityIssue.status == "open")):
            issue.status = "resolved"
    db.flush()
    _embed_chunks(list(db.scalars(select(DocumentChunk).where(
        DocumentChunk.document_id == doc.id, DocumentChunk.embedding.is_(None)))))
    job.rows_read, job.inserted = len(missing), len(missing) - still_empty
    job.status = "succeeded" if not still_empty else "partial"
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    return job


# ---------------------------------------------------------------- question bank

QUESTION_COLUMNS = ["chapter_code", "topic", "difficulty", "question", "option_1", "option_2", "option_3", "option_4",
                    "answer", "explanation"]


def import_questions(db: Session, content: bytes, filename: str, *, source_name: str, review_status: str,
                     data_source: DataSource | None, user_id: int | None = None) -> DataImportJob:
    """Import MCQs (answer = 1-4). Duplicates (same question and options) are skipped.

    review_status is "reviewed" only when the uploader confirms a subject expert checked every
    answer key; otherwise "draft", which is never shown to students.
    """
    from app.models import Question, SyllabusChapter
    from app.practice_seed import _hash

    if review_status not in ("draft", "reviewed"):
        raise ImportRefused("review_status must be draft or reviewed")
    sha, path = store_raw(content, filename)
    job = DataImportJob(kind="questions", filename=filename, data_version=sha[:12], triggered_by=user_id)
    db.add(job)
    db.flush()
    try:
        rows = read_table(content, filename)
    except Exception as exc:  # noqa: BLE001
        job.status, job.finished_at = "failed", datetime.now(timezone.utc)
        job.errors = [{"row": None, "error": f"Could not parse file: {exc}"}]
        db.commit()
        return job
    chapters = {c.code: c for c in db.scalars(select(SyllabusChapter))}
    existing = set(db.scalars(select(Question.content_hash)))
    errors = []
    for i, row in enumerate(rows, start=2):
        job.rows_read += 1
        opts = [row.get(f"option_{k}", "").strip() for k in range(1, 5)]
        ch = chapters.get((row.get("chapter_code") or "").strip().upper())
        diff = (row.get("difficulty") or "medium").strip().lower()
        problem = None
        if ch is None:
            problem = f"Unknown chapter_code '{row.get('chapter_code')}'"
        elif not row.get("question", "").strip() or not all(opts):
            problem = "Question and all four options are required"
        elif len(set(opts)) < 4:
            problem = "Options must be different from each other"
        elif (row.get("answer") or "").strip() not in ("1", "2", "3", "4"):
            problem = "answer must be 1, 2, 3 or 4"
        elif diff not in ("easy", "medium", "hard"):
            problem = "difficulty must be easy, medium or hard"
        if problem:
            errors.append({"row": i, "error": problem})
            job.skipped += 1
            continue
        h = _hash(row["question"], opts)
        if h in existing:
            job.skipped += 1
            continue
        existing.add(h)
        db.add(Question(subject=ch.subject, chapter_id=ch.id, topic=row.get("topic") or None, difficulty=diff,
                        stem=row["question"].strip(), options=opts, correct_index=int(row["answer"]) - 1,
                        explanation=row.get("explanation") or None, review_status=review_status, content_hash=h,
                        source_name=source_name, import_job_id=job.id,
                        verification_status=VerificationStatus.verified if review_status == "reviewed"
                        else VerificationStatus.unverified))
        job.inserted += 1
    job.errors = errors[:500]
    job.status = "succeeded" if not errors else ("partial" if job.inserted else "failed")
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    return job
