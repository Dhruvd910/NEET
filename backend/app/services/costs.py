"""Total-cost-of-attendance estimate built only from stored fee records.

Rules:
- Use a single academic year (the latest with fee data) — never silently mix years.
- Mandatory and optional charges are reported separately.
- Living expenses outside official charges are not estimated here (no verified data).
"""
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Course, FeeRecord, VerificationStatus

ANNUAL_MULTIPLIER = {"annual": 1, "monthly": 12}
HOSTEL_TYPES = {"hostel", "mess"}


@dataclass
class CostEstimate:
    college_id: int
    course_code: str | None
    quota: str
    academic_year: str | None
    available: bool
    annual_mandatory_inr: int = 0
    annual_hostel_mess_inr: int = 0
    one_time_inr: int = 0
    refundable_deposits_inr: int = 0
    estimated_annual_total_inr: int = 0
    estimated_full_course_inr: int = 0
    course_duration_years: float | None = None
    fee_lines: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    verification_statuses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_cost(db: Session, college_id: int, course_code: str | None = "MBBS",
                  quota: str = "ALL", include_hostel: bool = True) -> CostEstimate:
    course = db.scalar(select(Course).where(Course.code == course_code)) if course_code else None
    q = select(FeeRecord).where(FeeRecord.college_id == college_id)
    if course:
        q = q.where((FeeRecord.course_id == course.id) | (FeeRecord.course_id.is_(None)))
    rows = [r for r in db.scalars(q) if r.quota in (quota, "ALL")]

    est = CostEstimate(college_id=college_id, course_code=course_code, quota=quota,
                       academic_year=None, available=False,
                       course_duration_years=course.duration_years if course else None)
    if not rows:
        est.warnings.append("No fee records are available for this college yet.")
        return est

    years = sorted({r.academic_year for r in rows})
    year = years[-1]
    est.academic_year = year
    if len(years) > 1:
        est.warnings.append(
            f"Fee data exists for several academic years ({', '.join(years)}); only {year} is used. "
            "Fees for later years may differ.")
    rows = [r for r in rows if r.academic_year == year]
    # A quota-specific line overrides the generic "ALL" line of the same type.
    by_type: dict[str, FeeRecord] = {}
    for r in sorted(rows, key=lambda r: r.quota != "ALL"):
        by_type[r.fee_type] = r

    duration = course.duration_years if course else None
    for r in by_type.values():
        line = {
            "fee_type": r.fee_type, "amount_inr": r.amount_inr, "period": r.period,
            "mandatory": r.mandatory, "refundable": r.refundable, "quota": r.quota,
            "academic_year": r.academic_year, "source_name": r.source_name, "source_url": r.source_url,
            "verification_status": r.verification_status.value, "note": r.note,
        }
        est.fee_lines.append(line)
        est.verification_statuses.append(r.verification_status.value)
        if r.fee_type in HOSTEL_TYPES:
            if include_hostel and r.period in ANNUAL_MULTIPLIER:
                est.annual_hostel_mess_inr += r.amount_inr * ANNUAL_MULTIPLIER[r.period]
            continue
        if not r.mandatory:
            continue
        if r.period in ANNUAL_MULTIPLIER:
            est.annual_mandatory_inr += r.amount_inr * ANNUAL_MULTIPLIER[r.period]
        elif r.period == "one_time":
            if r.refundable:
                est.refundable_deposits_inr += r.amount_inr
            else:
                est.one_time_inr += r.amount_inr
        elif r.period == "course":
            est.one_time_inr += r.amount_inr

    est.available = True
    est.estimated_annual_total_inr = est.annual_mandatory_inr + est.annual_hostel_mess_inr
    if duration:
        # Fee-paying years exclude the internship year where the duration note says so; we keep
        # it simple and conservative: academic years = floor(duration).
        academic_years = int(duration)
        est.estimated_full_course_inr = est.estimated_annual_total_inr * academic_years + est.one_time_inr
        est.warnings.append(
            f"Full-course estimate assumes {year} fees stay constant for {academic_years} years; "
            "colleges often revise fees annually.")
    if "tuition" not in by_type:
        est.warnings.append("Tuition fee is missing for this year — the estimate is incomplete.")
    if include_hostel and not (HOSTEL_TYPES & by_type.keys()):
        est.warnings.append("Hostel/mess charges are not available; total excludes accommodation.")
    est.warnings.append("Personal living expenses (travel, books, food outside mess) are not included.")
    if any(s != VerificationStatus.verified.value for s in est.verification_statuses):
        est.warnings.append("Some fee lines are not verified against an official source.")
    return est
