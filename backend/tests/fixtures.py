"""Hand-built, clearly-labelled test fixtures with known cutoff values."""
import itertools

from sqlalchemy import select

from app.models import (
    College, CounsellingAuthority, Course, CutoffRecord, EligibilityRule, RankBasis, VerificationStatus,
)

_seq = itertools.count(1)
PROV = dict(source_name="TEST FIXTURE (synthetic)", verification_status=VerificationStatus.demo)


def make_college(db, state="Testland", itype="government") -> College:
    n = next(_seq)
    c = College(code=f"TEST-{n}", name=f"Test Fixture College {n} (TEST)", state=state, city="Testville",
                institution_type=itype, is_demo=True, **PROV)
    db.add(c)
    db.flush()
    return c


def ensure_authority(db, code="TST-STATE", state="Testland") -> CounsellingAuthority:
    a = db.scalar(select(CounsellingAuthority).where(CounsellingAuthority.code == code))
    if a is None:
        a = CounsellingAuthority(code=code, name=f"{code} authority", level="state", state=state,
                                 quotas=["STATE", "MANAGEMENT"])
        db.add(a)
        db.flush()
    return a


def add_series(db, college, authority_code, quota, category, closings_by_year: dict[int, int],
               basis=RankBasis.AIR, domicile=False, course="MBBS"):
    course_id = db.scalar(select(Course.id).where(Course.code == course))
    a = db.scalar(select(CounsellingAuthority).where(CounsellingAuthority.code == authority_code))
    for year, closing in closings_by_year.items():
        db.add(CutoffRecord(college_id=college.id, course_id=course_id, authority_id=a.id, exam_year=year,
                            round_number=1, quota=quota, category=category, closing_rank=int(closing * 0.8),
                            rank_basis=basis, domicile_required=domicile, **PROV))
        db.add(CutoffRecord(college_id=college.id, course_id=course_id, authority_id=a.id, exam_year=year,
                            round_number=2, quota=quota, category=category, closing_rank=closing,
                            rank_basis=basis, domicile_required=domicile, **PROV))
    db.flush()


def set_open_rule(db, authority_code, quota, years, value=True):
    a = db.scalar(select(CounsellingAuthority).where(CounsellingAuthority.code == authority_code))
    for y in years:
        r = db.scalar(select(EligibilityRule).filter_by(authority_id=a.id, exam_year=y, quota=quota,
                                                         rule_key="open_category_accessible"))
        if r is None:
            db.add(EligibilityRule(authority_id=a.id, exam_year=y, quota=quota, rule_key="open_category_accessible",
                                   rule_value={"value": value}, **PROV))
        else:
            r.rule_value = {"value": value}
    db.flush()
