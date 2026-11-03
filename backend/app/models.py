"""ORM models.

Every factual record (cutoffs, fees, seats, hostels, facilities, outcomes, ...) carries the
`Provenance` columns so the UI can always show source, academic year and verification status.
Historical rows are never overwritten across years: the academic/exam year is part of every
natural key.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VerificationStatus(str, enum.Enum):
    demo = "demo"                      # synthetic development data — never real
    unverified = "unverified"          # imported, not yet reviewed
    pending_review = "pending_review"  # flagged for a human
    verified = "verified"              # checked against the official source
    outdated = "outdated"              # superseded / stale
    conflicting = "conflicting"        # disagrees with another source


class Role(str, enum.Enum):
    student = "student"
    admin = "admin"


class RankType(str, enum.Enum):
    official = "official"
    estimated = "estimated"


class RankBasis(str, enum.Enum):
    AIR = "AIR"
    STATE_RANK = "STATE_RANK"


class Provenance:
    """Mixin: source & freshness metadata attached to every factual record."""

    source_name: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(500))
    publication_date: Mapped[date | None] = mapped_column(Date)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, native_enum=False), default=VerificationStatus.unverified
    )

    @declared_attr
    def source_document_id(cls) -> Mapped[int | None]:
        return mapped_column(ForeignKey("source_documents.id", ondelete="SET NULL"))

    @declared_attr
    def import_job_id(cls) -> Mapped[int | None]:
        return mapped_column(ForeignKey("data_import_jobs.id", ondelete="SET NULL"))


# ---------------------------------------------------------------- users & students

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True, index=True)  # empty for phone-only accounts
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), default=Role.student)
    is_minor: Mapped[bool] = mapped_column(Boolean, default=False)
    guardian_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    # Minors: not_required (adult) / pending / verified / declined. Personal-data features stay locked
    # until a guardian confirms through the emailed link (see routers/auth.py).
    guardian_consent_status: Mapped[str] = mapped_column(String(20), default="not_required")
    guardian_email: Mapped[str | None] = mapped_column(String(254))
    guardian_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    guardian_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    guardian_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Phone sign-in (Tekurious AI-Auth): verified phone in E.164 form and Tekurious's user id.
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    tekurious_user_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    # Google sign-in: Google's stable account id ("sub"), and the name Google shares.
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(120))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    profile: Mapped[StudentProfile | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False)

    @property
    def label(self) -> str:
        """How to refer to the person on screen: their name, else email, else phone."""
        return self.name or self.email or self.phone or f"User {self.id}"


class LoginEvent(Base):
    """One row per successful sign-in, for the admin's sign-in history. Kept for LOGIN_HISTORY_DAYS, then purged."""
    __tablename__ = "login_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    method: Mapped[str] = mapped_column(String(20))  # password / phone / google / signup
    ip_prefix: Mapped[str | None] = mapped_column(String(45))  # last part removed, e.g. 203.0.113.x
    user_agent: Mapped[str | None] = mapped_column(String(200))


class StudentProfile(Base):
    __tablename__ = "student_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(80))
    current_class: Mapped[str | None] = mapped_column(String(20))  # "11", "12", "dropper", "graduated"
    academic_year: Mapped[str | None] = mapped_column(String(9))   # "2026-27"
    state: Mapped[str | None] = mapped_column(String(60))
    domicile_state: Mapped[str | None] = mapped_column(String(60))
    class10_percentage: Mapped[float | None] = mapped_column(Float)
    class12_status: Mapped[str | None] = mapped_column(String(30))  # appearing / passed
    # Category & sub-category are sensitive: only used for counselling-rule calculations.
    category: Mapped[str | None] = mapped_column(String(20))
    sub_category: Mapped[str | None] = mapped_column(String(40))
    pwd: Mapped[bool | None] = mapped_column(Boolean)
    preferred_course: Mapped[str | None] = mapped_column(String(20))
    preferred_states: Mapped[list] = mapped_column(JSON, default=list)
    institution_preferences: Mapped[list] = mapped_column(JSON, default=list)
    budget_max_annual: Mapped[int | None] = mapped_column(Integer)
    hostel_required: Mapped[bool | None] = mapped_column(Boolean)
    language: Mapped[str] = mapped_column(String(10), default="en")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="profile")


class AcademicRecord(Base):
    __tablename__ = "academic_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(10))  # "10", "11", "12"
    subject: Mapped[str] = mapped_column(String(40))
    marks: Mapped[float] = mapped_column(Float)
    max_marks: Mapped[float] = mapped_column(Float)
    year: Mapped[int | None] = mapped_column(Integer)


class ExamProfile(Base):
    __tablename__ = "exam_profiles"
    __table_args__ = (UniqueConstraint("user_id", "exam_year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    exam_year: Mapped[int] = mapped_column(Integer)
    has_taken: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[int | None] = mapped_column(Integer)
    percentile: Mapped[float | None] = mapped_column(Float)
    air: Mapped[int | None] = mapped_column(Integer)
    state_rank: Mapped[int | None] = mapped_column(Integer)
    rank_type: Mapped[RankType] = mapped_column(Enum(RankType, native_enum=False), default=RankType.official)
    # Only for estimated ranks: a range, never a single falsely-precise number.
    estimated_rank_low: Mapped[int | None] = mapped_column(Integer)
    estimated_rank_high: Mapped[int | None] = mapped_column(Integer)
    estimate_basis: Mapped[str | None] = mapped_column(Text)


class MockTest(Base):
    __tablename__ = "mock_tests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str | None] = mapped_column(String(120))
    test_date: Mapped[date] = mapped_column(Date)
    total_score: Mapped[float] = mapped_column(Float)
    max_score: Mapped[float] = mapped_column(Float, default=720)
    percentile: Mapped[float | None] = mapped_column(Float)
    provider_rank: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    subjects: Mapped[list[MockTestSubjectScore]] = relationship(
        back_populates="test", cascade="all, delete-orphan", lazy="selectin")


class MockTestSubjectScore(Base):
    __tablename__ = "mock_test_subject_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    mock_test_id: Mapped[int] = mapped_column(ForeignKey("mock_tests.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(20))  # Physics / Chemistry / Biology
    score: Mapped[float] = mapped_column(Float)
    max_score: Mapped[float] = mapped_column(Float)
    weak_topics: Mapped[list] = mapped_column(JSON, default=list)

    test: Mapped[MockTest] = relationship(back_populates="subjects")


class RoadmapItem(Base):
    __tablename__ = "roadmap_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30))  # study / admission / counselling
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="todo")
    generated: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------- data provenance

class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))  # official_portal / college_site / licensed_api / demo
    base_url: Mapped[str | None] = mapped_column(String(500))
    terms_note: Mapped[str | None] = mapped_column(Text)
    automated_access_permitted: Mapped[bool] = mapped_column(Boolean, default=False)
    # Terms-of-use review. Imports that name a source are refused unless usage_status == "allowed".
    usage_status: Mapped[str] = mapped_column(String(20), default="unreviewed")  # unreviewed/allowed/restricted/prohibited
    terms_url: Mapped[str | None] = mapped_column(String(500))
    attribution_text: Mapped[str | None] = mapped_column(String(300))
    terms_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms_reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class SourceDocument(Base):
    __tablename__ = "source_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    data_source_id: Mapped[int | None] = mapped_column(ForeignKey("data_sources.id"))
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(500))
    authority: Mapped[str | None] = mapped_column(String(40))
    doc_type: Mapped[str] = mapped_column(String(40))  # bulletin / notice / seat_matrix / cutoff / prospectus
    academic_year: Mapped[str | None] = mapped_column(String(9))
    exam_year: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str | None] = mapped_column(String(60))
    course_code: Mapped[str | None] = mapped_column(String(20))
    publication_date: Mapped[date | None] = mapped_column(Date)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    stored_path: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, default=1)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, native_enum=False), default=VerificationStatus.unverified)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    """Text chunks for retrieval: BM25 keyword ranking, plus embeddings when a provider is configured."""
    __tablename__ = "document_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id", ondelete="CASCADE"), index=True)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    extraction: Mapped[str] = mapped_column(String(20), default="text")  # text / ocr
    embedding: Mapped[list | None] = mapped_column(JSON)
    embedding_model: Mapped[str | None] = mapped_column(String(80))

    document: Mapped[SourceDocument] = relationship(back_populates="chunks")


class DataImportJob(Base):
    __tablename__ = "data_import_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))  # cutoffs / seat_matrix / fees / document
    status: Mapped[str] = mapped_column(String(20), default="running")  # running/succeeded/failed/partial
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id"))
    filename: Mapped[str | None] = mapped_column(String(300))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    data_version: Mapped[str | None] = mapped_column(String(40))
    triggered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    issue_type: Mapped[str] = mapped_column(String(40))  # unknown_college / conflict / invalid_row / duplicate
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open / resolved / ignored
    import_job_id: Mapped[int | None] = mapped_column(ForeignKey("data_import_jobs.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    changes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConsentRecord(Base):
    """Append-only record of consents given or withdrawn (privacy notice, guardian consent)."""
    __tablename__ = "consent_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # privacy_notice / guardian_consent
    action: Mapped[str] = mapped_column(String(20))  # granted / declined / withdrawn / requested
    notice_version: Mapped[str] = mapped_column(String(20))
    method: Mapped[str] = mapped_column(String(40))  # signup_checkbox / guardian_email_link
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- catalog

class University(Base):
    __tablename__ = "universities"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    state: Mapped[str | None] = mapped_column(String(60))
    website: Mapped[str | None] = mapped_column(String(300))


class College(Base, Provenance):
    __tablename__ = "colleges"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)  # stable canonical id
    name: Mapped[str] = mapped_column(String(250), index=True)
    state: Mapped[str] = mapped_column(String(60), index=True)
    city: Mapped[str | None] = mapped_column(String(80))
    address: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    institution_type: Mapped[str] = mapped_column(String(30))  # government / private / deemed / central / aiims ...
    university_id: Mapped[int | None] = mapped_column(ForeignKey("universities.id"))
    established_year: Mapped[int | None] = mapped_column(Integer)
    website: Mapped[str | None] = mapped_column(String(300))
    recognition_status: Mapped[str | None] = mapped_column(String(120))
    recognition_year: Mapped[str | None] = mapped_column(String(9))
    recognition_note: Mapped[str | None] = mapped_column(Text)  # the regulator's full remark, as published
    pincode: Mapped[str | None] = mapped_column(String(10))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    contact_phone: Mapped[str | None] = mapped_column(String(60))
    # Where the website and map location came from; these are matched automatically, so they are shown separately.
    website_source: Mapped[str | None] = mapped_column(String(120))
    location_source: Mapped[str | None] = mapped_column(String(120))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    university: Mapped[University | None] = relationship(lazy="joined")
    aliases: Mapped[list[CollegeAlias]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    courses: Mapped[list[CollegeCourse]] = relationship(back_populates="college", cascade="all, delete-orphan")


class CollegeAlias(Base):
    __tablename__ = "college_aliases"
    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"), index=True)
    alias: Mapped[str] = mapped_column(String(250))
    normalized: Mapped[str] = mapped_column(String(250), unique=True, index=True)


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # MBBS / BDS / BAMS ...
    name: Mapped[str] = mapped_column(String(200))
    duration_years: Mapped[float] = mapped_column(Float)  # includes internship where applicable
    duration_note: Mapped[str | None] = mapped_column(String(200))
    entrance_exam: Mapped[str | None] = mapped_column(String(60))


class CollegeCourse(Base, Provenance):
    __tablename__ = "college_courses"
    __table_args__ = (UniqueConstraint("college_id", "course_id", "academic_year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    academic_year: Mapped[str] = mapped_column(String(9))
    approved_intake: Mapped[int | None] = mapped_column(Integer)

    college: Mapped[College] = relationship(back_populates="courses")
    course: Mapped[Course] = relationship(lazy="joined")


class CounsellingAuthority(Base):
    __tablename__ = "counselling_authorities"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)  # MCC, KEA, ...
    name: Mapped[str] = mapped_column(String(200))
    level: Mapped[str] = mapped_column(String(10))  # central / state
    state: Mapped[str | None] = mapped_column(String(60))
    website: Mapped[str | None] = mapped_column(String(300))
    # quotas this authority runs, e.g. ["AIQ","DEEMED","CENTRAL"] or ["STATE","MANAGEMENT"]
    quotas: Mapped[list] = mapped_column(JSON, default=list)


class CounsellingRound(Base, Provenance):
    __tablename__ = "counselling_rounds"
    __table_args__ = (UniqueConstraint("authority_id", "exam_year", "round_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    authority_id: Mapped[int] = mapped_column(ForeignKey("counselling_authorities.id"))
    exam_year: Mapped[int] = mapped_column(Integer)
    round_number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(80))
    registration_start: Mapped[date | None] = mapped_column(Date)
    registration_end: Mapped[date | None] = mapped_column(Date)
    result_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


class SeatMatrix(Base, Provenance):
    __tablename__ = "seat_matrices"
    __table_args__ = (UniqueConstraint(
        "college_id", "course_id", "authority_id", "exam_year", "round_number", "quota", "category", "seat_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    authority_id: Mapped[int] = mapped_column(ForeignKey("counselling_authorities.id"))
    exam_year: Mapped[int] = mapped_column(Integer)
    round_number: Mapped[int] = mapped_column(Integer)
    quota: Mapped[str] = mapped_column(String(30))
    category: Mapped[str] = mapped_column(String(20))
    seat_type: Mapped[str] = mapped_column(String(30), default="GENERAL")
    seats: Mapped[int] = mapped_column(Integer)


class CutoffRecord(Base, Provenance):
    __tablename__ = "cutoff_records"
    __table_args__ = (
        UniqueConstraint("college_id", "course_id", "authority_id", "exam_year", "round_number",
                         "quota", "category", "seat_type", name="uq_cutoff_natural_key"),
        Index("ix_cutoff_lookup", "course_id", "authority_id", "quota", "category", "exam_year"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    authority_id: Mapped[int] = mapped_column(ForeignKey("counselling_authorities.id"))
    exam_year: Mapped[int] = mapped_column(Integer)
    round_number: Mapped[int] = mapped_column(Integer)
    round_name: Mapped[str | None] = mapped_column(String(60))
    quota: Mapped[str] = mapped_column(String(30))       # AIQ / STATE / DEEMED / CENTRAL / MANAGEMENT / NRI
    category: Mapped[str] = mapped_column(String(20))    # normalised: OPEN / OBC / SC / ST / EWS ...
    seat_type: Mapped[str] = mapped_column(String(30), default="GENERAL")  # GENERAL / PWD / ...
    domicile_required: Mapped[bool] = mapped_column(Boolean, default=False)
    rank_basis: Mapped[RankBasis] = mapped_column(Enum(RankBasis, native_enum=False), default=RankBasis.AIR)
    opening_rank: Mapped[int | None] = mapped_column(Integer)
    closing_rank: Mapped[int] = mapped_column(Integer)

    college: Mapped[College] = relationship(lazy="joined")
    course: Mapped[Course] = relationship(lazy="joined")
    authority: Mapped[CounsellingAuthority] = relationship(lazy="joined")


class AllotmentRecord(Base, Provenance):
    __tablename__ = "allotment_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    authority_id: Mapped[int] = mapped_column(ForeignKey("counselling_authorities.id"))
    exam_year: Mapped[int] = mapped_column(Integer)
    round_number: Mapped[int] = mapped_column(Integer)
    quota: Mapped[str] = mapped_column(String(30))
    allotted_category: Mapped[str] = mapped_column(String(20))
    candidate_category: Mapped[str | None] = mapped_column(String(20))
    seat_type: Mapped[str] = mapped_column(String(30), default="GENERAL")
    rank: Mapped[int] = mapped_column(Integer)


class EligibilityRule(Base, Provenance):
    """Machine-readable admission rules, always scoped to an authority and year.

    Known keys used by the predictor:
      - open_category_accessible (bool): reserved-category candidates may also be compared
        against OPEN-category closing ranks.
      - state_quota_rank_basis ("AIR" | "STATE_RANK")
    A missing rule is treated as "not verified", never as a default truth.
    """
    __tablename__ = "eligibility_rules"
    __table_args__ = (UniqueConstraint("authority_id", "exam_year", "quota", "rule_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    authority_id: Mapped[int] = mapped_column(ForeignKey("counselling_authorities.id"))
    exam_year: Mapped[int] = mapped_column(Integer)
    quota: Mapped[str] = mapped_column(String(30), default="*")
    rule_key: Mapped[str] = mapped_column(String(60))
    rule_value: Mapped[dict] = mapped_column(JSON)
    description: Mapped[str | None] = mapped_column(Text)


class FeeRecord(Base, Provenance):
    __tablename__ = "fee_records"
    __table_args__ = (UniqueConstraint("college_id", "course_id", "academic_year", "quota", "fee_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"))
    academic_year: Mapped[str] = mapped_column(String(9))
    quota: Mapped[str] = mapped_column(String(30), default="ALL")
    # tuition / admission / exam / security_deposit / hostel / mess / other
    fee_type: Mapped[str] = mapped_column(String(30))
    amount_inr: Mapped[int] = mapped_column(Integer)
    period: Mapped[str] = mapped_column(String(20))  # annual / one_time / monthly / course
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    refundable: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)


class HostelRecord(Base, Provenance):
    __tablename__ = "hostel_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"), index=True)
    on_campus: Mapped[bool] = mapped_column(Boolean, default=True)
    provider_name: Mapped[str | None] = mapped_column(String(200))  # for off-campus PGs
    gender: Mapped[str | None] = mapped_column(String(20))  # boys / girls / all
    hostel_count: Mapped[int | None] = mapped_column(Integer)
    capacity: Mapped[int | None] = mapped_column(Integer)
    room_types: Mapped[list] = mapped_column(JSON, default=list)
    facilities: Mapped[list] = mapped_column(JSON, default=list)
    rules_note: Mapped[str | None] = mapped_column(Text)
    rent_min_inr: Mapped[int | None] = mapped_column(Integer)
    rent_max_inr: Mapped[int | None] = mapped_column(Integer)
    rent_period: Mapped[str | None] = mapped_column(String(20))
    distance_km: Mapped[float | None] = mapped_column(Float)
    availability_note: Mapped[str | None] = mapped_column(Text)


class Facility(Base, Provenance):
    __tablename__ = "facilities"
    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(30))  # academic / clinical / research / campus / internship
    name: Mapped[str] = mapped_column(String(200))
    details: Mapped[str | None] = mapped_column(Text)
    numeric_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(30))


class OutcomeRecord(Base, Provenance):
    __tablename__ = "placement_or_outcome_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(80))  # internship_stipend_monthly / pg_pathway_note ...
    value_text: Mapped[str | None] = mapped_column(Text)
    value_numeric: Mapped[float | None] = mapped_column(Float)
    year: Mapped[str | None] = mapped_column(String(9))
    comparable: Mapped[bool] = mapped_column(Boolean, default=False)


class NearbyPlace(Base):
    __tablename__ = "nearby_places"
    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # bus_stop / railway / metro / airport / pharmacy / ...
    name: Mapped[str] = mapped_column(String(200))
    distance_km: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    route_url: Mapped[str | None] = mapped_column(String(500))
    price_range: Mapped[str | None] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(60))  # licensed maps/places provider, or "demo"
    attribution: Mapped[str | None] = mapped_column(String(200))
    external_id: Mapped[str | None] = mapped_column(String(80))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class StudentReview(Base):
    __tablename__ = "student_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    rating: Mapped[int] = mapped_column(Integer)  # 1-5
    aspect_ratings: Mapped[dict] = mapped_column(JSON, default=dict)  # academics / hostel / mess ...
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending / approved / rejected
    moderation_note: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SavedCollege(Base):
    __tablename__ = "saved_colleges"
    __table_args__ = (UniqueConstraint("user_id", "college_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    college_id: Mapped[int] = mapped_column(ForeignKey("colleges.id", ondelete="CASCADE"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CollegeComparison(Base):
    __tablename__ = "college_comparisons"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    college_ids: Mapped[list] = mapped_column(JSON)
    priorities: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PreferenceList(Base):
    __tablename__ = "preference_lists"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    authority_code: Mapped[str] = mapped_column(String(30))
    exam_year: Mapped[int] = mapped_column(Integer)
    course_code: Mapped[str] = mapped_column(String(20))
    # [{college_id, quota, note, historical_fit}] in the STUDENT's order
    items: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # always a draft; never submitted
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class InfoArticle(Base, Provenance):
    """NEET information hub & career pathways content, each with exam year and source."""
    __tablename__ = "info_articles"
    id: Mapped[int] = mapped_column(primary_key=True)
    section: Mapped[str] = mapped_column(String(30))  # neet / counselling / careers / faq
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    exam_year: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    messages: Mapped[list[ChatMessage]] = relationship(
        cascade="all, delete-orphan", order_by="ChatMessage.id", lazy="selectin")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[list] = mapped_column(JSON, default=list)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- practice: syllabus, questions, exams, plans

class SyllabusChapter(Base, Provenance):
    """A chapter of the NEET-UG syllabus. Planning hours are rough estimates, not official data."""
    __tablename__ = "syllabus_chapters"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # e.g. PHY-11-04
    subject: Mapped[str] = mapped_column(String(20), index=True)  # Physics / Chemistry / Botany / Zoology
    class_level: Mapped[str] = mapped_column(String(4))  # "11" / "12"
    name: Mapped[str] = mapped_column(String(160))
    est_hours: Mapped[int] = mapped_column(Integer, default=12)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text)


class Question(Base, Provenance):
    """A multiple-choice question with exactly four options.

    review_status: draft (never served) / sample (served with a "not expert-reviewed" label) /
    ai_checked (AI-written, answer confirmed by an independent model; served with a label) /
    reviewed (checked by a subject expert) / flagged (reported by students; hidden) / retired.
    """
    __tablename__ = "questions"
    __table_args__ = (Index("ix_question_pick", "subject", "chapter_id", "review_status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String(20))
    chapter_id: Mapped[int] = mapped_column(ForeignKey("syllabus_chapters.id"), index=True)
    topic: Mapped[str | None] = mapped_column(String(160))
    difficulty: Mapped[str] = mapped_column(String(10), default="medium")  # easy / medium / hard
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON)  # 4 strings
    correct_index: Mapped[int] = mapped_column(Integer)  # 0-3
    explanation: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(12), default="draft")
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # single / statements / assertion_reason / match (the NEET question styles)
    qformat: Mapped[str] = mapped_column(String(20), default="single")
    generated_by: Mapped[str | None] = mapped_column(String(120))
    checked_by: Mapped[str | None] = mapped_column(String(120))
    report_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chapter: Mapped[SyllabusChapter] = relationship(lazy="joined")


class QuestionReport(Base):
    """A student's report that a question or its answer key looks wrong."""
    __tablename__ = "question_reports"
    __table_args__ = (UniqueConstraint("question_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(String(30))  # wrong_answer / unclear / out_of_syllabus / typo / other
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="open")  # open / fixed / dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExamAttempt(Base):
    """One sitting of a timed test. Correct answers are copied in at creation, so later edits to the
    question bank never change a past result."""
    __tablename__ = "exam_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(20))  # full / mini / subject / chapter / weak
    title: Mapped[str] = mapped_column(String(160))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    pattern: Mapped[dict] = mapped_column(JSON, default=dict)
    strict_omr: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(15), default="in_progress")  # ready / in_progress / submitted
    booklet_code: Mapped[str | None] = mapped_column(String(4))
    roll_number: Mapped[str | None] = mapped_column(String(12))
    auto_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    focus_lost_count: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int | None] = mapped_column(Integer)
    max_score: Mapped[int] = mapped_column(Integer)
    mock_test_id: Mapped[int | None] = mapped_column(ForeignKey("mock_tests.id", ondelete="SET NULL"))

    items: Mapped[list[ExamAttemptItem]] = relationship(
        cascade="all, delete-orphan", order_by="ExamAttemptItem.position", lazy="selectin")


class ExamAttemptItem(Base):
    __tablename__ = "exam_attempt_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("exam_attempts.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    position: Mapped[int] = mapped_column(Integer)  # 1-based question number
    section: Mapped[str] = mapped_column(String(20))
    correct_index: Mapped[int] = mapped_column(Integer)
    selected_index: Mapped[int | None] = mapped_column(Integer)
    marked_for_review: Mapped[bool] = mapped_column(Boolean, default=False)
    visited: Mapped[bool] = mapped_column(Boolean, default=False)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, default=0)

    question: Mapped[Question] = relationship(lazy="joined")


class ChapterProgress(Base):
    __tablename__ = "chapter_progress"
    __table_args__ = (UniqueConstraint("user_id", "chapter_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("syllabus_chapters.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(15), default="not_started")  # not_started/learning/revised/mastered
    confidence: Mapped[int | None] = mapped_column(Integer)  # 1-5, self-rated
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class StudyPlan(Base):
    __tablename__ = "study_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    current_class: Mapped[str] = mapped_column(String(20))
    start_date: Mapped[date] = mapped_column(Date)
    exam_date: Mapped[date] = mapped_column(Date)
    exam_date_is_estimate: Mapped[bool] = mapped_column(Boolean, default=True)
    weekday_hours: Mapped[float] = mapped_column(Float)
    weekend_hours: Mapped[float] = mapped_column(Float)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tasks: Mapped[list[StudyTask]] = relationship(
        cascade="all, delete-orphan", order_by="StudyTask.week_index, StudyTask.id", lazy="selectin")


class StudyTask(Base):
    __tablename__ = "study_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("study_plans.id", ondelete="CASCADE"), index=True)
    week_index: Mapped[int] = mapped_column(Integer)
    week_start: Mapped[date] = mapped_column(Date)
    phase: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(15))  # learn / revise / practice / mock / board
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("syllabus_chapters.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text)
    est_hours: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(10), default="todo")  # todo / done
