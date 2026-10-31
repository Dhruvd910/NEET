from datetime import date

from sqlalchemy import select

from app.models import CutoffRecord, DataQualityIssue, FeeRecord, VerificationStatus
from app.services.costs import estimate_cost
from app.services.ingestion import import_cutoffs
from app.services.mock_analytics import analyse
from tests.fixtures import PROV, make_college


def fee(db, c, ftype, amount, period, year="2025-26", mandatory=True, refundable=False):
    db.add(FeeRecord(college_id=c.id, course_id=None, academic_year=year, fee_type=ftype, amount_inr=amount,
                     period=period, mandatory=mandatory, refundable=refundable, **PROV))
    db.flush()


def test_cost_uses_one_year_and_warns_on_mixed_years(db):
    c = make_college(db)
    fee(db, c, "tuition", 100000, "annual", year="2024-25")
    fee(db, c, "tuition", 120000, "annual")
    fee(db, c, "hostel", 30000, "annual", mandatory=False)
    fee(db, c, "mess", 4000, "monthly", mandatory=False)
    fee(db, c, "admission", 10000, "one_time")
    fee(db, c, "security_deposit", 25000, "one_time", refundable=True)
    est = estimate_cost(db, c.id, "MBBS")
    assert est.academic_year == "2025-26"
    assert any("several academic years" in w for w in est.warnings)
    assert est.annual_mandatory_inr == 120000
    assert est.annual_hostel_mess_inr == 30000 + 4000 * 12
    assert est.one_time_inr == 10000 and est.refundable_deposits_inr == 25000
    assert est.estimated_full_course_inr == (120000 + 78000) * 5 + 10000
    assert all(line["academic_year"] == "2025-26" for line in est.fee_lines)
    assert any("not verified" in w for w in est.warnings)


def test_cost_unavailable_without_fees(db):
    est = estimate_cost(db, make_college(db).id)
    assert not est.available and est.estimated_annual_total_inr == 0


CSV = """college_code,course,authority,exam_year,round,quota,category,seat_type,rank_basis,opening_rank,closing_rank
{code},MBBS,MCC,2025,1,All India Quota,UR,,AIR,100,5000
{code},MBBS,MCC,2025,2,AIQ,OBC-NCL,,AIR,200,6000
UNKNOWN-X,MBBS,MCC,2025,1,AIQ,UR,,AIR,1,10
{code},MBBS,MCC,2025,1,AIQ,ALIEN,,AIR,1,10
{code},MBBS,MCC,2025,3,AIQ,UR,,AIR,900,100
"""


def test_cutoff_import_validates_and_is_idempotent(db):
    c = make_college(db)
    db.commit()
    content = CSV.format(code=c.code).encode()
    job = import_cutoffs(db, content, "cutoffs.csv", source_name="Test source", source_url=None,
                         publication_date=date(2025, 9, 1))
    assert (job.rows_read, job.inserted, job.skipped) == (5, 2, 3)
    assert job.status == "partial"
    errors = " ".join(e["error"] for e in job.errors)
    assert "Unknown college" in errors and "category" in errors and "opening_rank" in errors
    issues = db.scalars(select(DataQualityIssue).where(DataQualityIssue.import_job_id == job.id)).all()
    assert {i.issue_type for i in issues} == {"unknown_college", "invalid_row"}
    rows = db.scalars(select(CutoffRecord).where(CutoffRecord.college_id == c.id)).all()
    assert {(r.quota, r.category) for r in rows} == {("AIQ", "OPEN"), ("AIQ", "OBC")}
    assert all(r.source_name == "Test source" and r.source_document_id for r in rows)

    again = import_cutoffs(db, content, "cutoffs.csv", source_name="Test source", source_url=None,
                           publication_date=None)
    assert again.inserted == 0 and again.updated == 0
    assert len(db.scalars(select(CutoffRecord).where(CutoffRecord.college_id == c.id)).all()) == 2


def test_import_does_not_overwrite_verified_records(db):
    c = make_college(db)
    db.commit()
    first = f"college_code,course,authority,exam_year,round,quota,category,closing_rank\n{c.code},MBBS,MCC,2025,1,AIQ,UR,5000\n"
    import_cutoffs(db, first.encode(), "a.csv", source_name="Official", source_url=None, publication_date=None)
    rec = db.scalar(select(CutoffRecord).where(CutoffRecord.college_id == c.id))
    rec.verification_status = VerificationStatus.verified
    db.commit()

    changed = first.replace("5000", "5200").encode()
    job = import_cutoffs(db, changed, "b.csv", source_name="Other", source_url=None, publication_date=None)
    db.refresh(rec)
    assert rec.closing_rank == 5000
    assert rec.verification_status == VerificationStatus.conflicting
    assert job.updated == 0
    assert db.scalar(select(DataQualityIssue).where(DataQualityIssue.entity_id == rec.id,
                                                    DataQualityIssue.issue_type == "conflict"))


def test_unparseable_file_fails_cleanly(db):
    job = import_cutoffs(db, b"\xff\xfe\x00garbage", "bad.csv", source_name="x", source_url=None, publication_date=None)
    assert job.status == "failed" and job.errors


def test_mock_estimate_is_labelled_band(db):
    class T:  # light stand-in for MockTest rows
        def __init__(self, i, score):
            from datetime import date as d
            self.id, self.name, self.provider, self.test_date = i, f"t{i}", None, d(2025, 1, i + 1)
            self.total_score, self.max_score, self.subjects = score, 720, []
    out = analyse([T(i, s) for i, s in enumerate([500, 540, 520, 560])])
    assert "not official" in out["notice"].lower()
    est = out["estimate"]
    assert "Estimate only" in est["label"]
    lo, hi = est["score_band_out_of_720"]
    assert lo <= 500 and hi >= 560 and est["assumptions"]
