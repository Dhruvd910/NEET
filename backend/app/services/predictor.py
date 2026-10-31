"""Transparent historical-cutoff matching baseline.

This is deliberately NOT a probability model. It compares the student's rank with historical
final-round closing ranks for exactly the same (course, authority, quota, category, seat type)
and assigns a guidance label. No admission is ever implied to be guaranteed.

Key rules
- Ranks are compared with ranks of the same basis (AIR vs state rank). Scores are never
  converted to ranks here: score→rank relationships change every year.
- Counselling routes (AIQ / STATE / DEEMED / CENTRAL / MANAGEMENT ...) are never mixed:
  each result row belongs to one authority + quota.
- State-quota rows that require domicile are only compared for students of that state.
- Reserved-category students are compared with OPEN rows only if a stored eligibility rule
  for that authority/year says OPEN seats are accessible; otherwise a caveat is shown.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CounsellingAuthority, Course, CutoffRecord, EligibilityRule, HostelRecord, RankBasis,
    RankType, VerificationStatus,
)
from app.services.costs import estimate_cost
from app.services.normalize import normalize_category

STRONGER = "Stronger historical fit"
POSSIBLE = "Possible / uncertain"
AMBITIOUS = "Ambitious"
FIT_ORDER = {STRONGER: 0, POSSIBLE: 1, AMBITIOUS: 2}

STRONGER_MARGIN = 0.90   # rank must be ≥10% better than the toughest year's closing rank
AMBITIOUS_STRETCH = 1.15  # up to 15% beyond the most lenient year's closing rank

DISCLAIMER = (
    "These are guidance labels based on past counselling data, not predictions of admission. "
    "Actual outcomes depend on this year's applicants, seat matrix, candidates' choices, "
    "eligibility verification and the counselling authority's rules. No admission is guaranteed."
)


class PredictorInputError(ValueError):
    pass


@dataclass
class PredictorInput:
    course_code: str
    exam_year: int
    rank_type: RankType
    air: int | None = None
    state_rank: int | None = None
    air_low: int | None = None    # estimated range (rank_type == estimated)
    air_high: int | None = None
    category: str | None = None
    pwd: bool = False
    domicile_state: str | None = None
    quotas: list[str] = field(default_factory=lambda: ["AIQ", "STATE"])
    preferred_states: list[str] = field(default_factory=list)
    institution_types: list[str] = field(default_factory=list)
    budget_max_annual: int | None = None
    hostel_required: bool = False
    years_considered: int = 3

    def validate(self) -> None:
        if self.rank_type == RankType.official:
            if not self.air and not self.state_rank:
                raise PredictorInputError("Enter your official AIR or state rank.")
            for v in (self.air, self.state_rank):
                if v is not None and v <= 0:
                    raise PredictorInputError("Ranks must be positive whole numbers.")
        else:
            if not (self.air_low and self.air_high):
                raise PredictorInputError(
                    "For an estimated rank, enter a range (lowest and highest likely AIR).")
            if self.air_low <= 0 or self.air_low > self.air_high:
                raise PredictorInputError("Estimated rank range is invalid (low must be ≤ high).")
        if not 1 <= self.years_considered <= 10:
            raise PredictorInputError("years_considered must be between 1 and 10.")
        if not self.quotas:
            raise PredictorInputError("Choose at least one counselling route/quota.")


def _rule(db: Session, authority_id: int, year: int, quota: str, key: str, demo: bool = False):
    """Value of a rule for an authority/year/quota, or None when no usable rule exists.

    Real data only uses *verified* rules; demo rules apply to demo colleges only, so a demo rule
    can never widen comparisons for real cutoff records.
    """
    usable = [VerificationStatus.verified] + ([VerificationStatus.demo] if demo else [])
    rows = db.scalars(select(EligibilityRule).where(
        EligibilityRule.authority_id == authority_id, EligibilityRule.exam_year == year,
        EligibilityRule.rule_key == key, EligibilityRule.quota.in_([quota, "*"]),
        EligibilityRule.verification_status.in_(usable))).all()
    rows.sort(key=lambda r: r.quota == "*")  # quota-specific wins
    return rows[0].rule_value.get("value") if rows else None


def _student_ranks(inp: PredictorInput, basis: RankBasis) -> tuple[int, int, bool] | None:
    """(optimistic, conservative, is_estimated) rank for a comparison basis, or None."""
    if basis == RankBasis.AIR:
        if inp.rank_type == RankType.official and inp.air:
            return inp.air, inp.air, False
        if inp.rank_type == RankType.estimated:
            return inp.air_low, inp.air_high, True
        return None
    if inp.rank_type == RankType.official and inp.state_rank:
        return inp.state_rank, inp.state_rank, False
    return None


def classify(rank_opt: int, rank_cons: int, closings: list[int]) -> str | None:
    toughest, most_lenient = min(closings), max(closings)
    if rank_cons <= toughest * STRONGER_MARGIN:
        return STRONGER
    if rank_opt <= most_lenient:
        return POSSIBLE
    if rank_opt <= most_lenient * AMBITIOUS_STRETCH:
        return AMBITIOUS
    return None


def confidence(closings: list[int], estimated: bool, demo: bool) -> tuple[str, str]:
    n = len(closings)
    vol = (max(closings) - min(closings)) / mean(closings) if n > 1 else None
    if n >= 3 and vol is not None and vol < 0.25:
        level = "higher"
    elif n >= 2 and vol is not None and vol < 0.5:
        level = "moderate"
    else:
        level = "low"
    if estimated and level == "higher":
        level = "moderate"
    reasons = [f"{n} year(s) of comparable data"]
    if vol is not None:
        reasons.append(f"closing ranks varied by {round(vol * 100)}% across years")
    if estimated:
        reasons.append("your rank is an estimate")
    if demo:
        reasons.append("DEMO data — not real counselling records")
    return level, "; ".join(reasons)


def predict(db: Session, inp: PredictorInput) -> dict:
    inp.validate()
    course = db.scalar(select(Course).where(Course.code == inp.course_code))
    if course is None:
        raise PredictorInputError(f"Course {inp.course_code} is not supported yet.")

    student_cat = normalize_category(inp.category) if inp.category else None
    global_caveats: list[str] = []
    if inp.category and student_cat is None:
        raise PredictorInputError(f"Unrecognised category '{inp.category}'.")
    if student_cat is None:
        student_cat = "OPEN"
        global_caveats.append("No category provided — compared against OPEN-category closing ranks only.")
    if inp.rank_type == RankType.estimated:
        global_caveats.append(
            "You entered an ESTIMATED rank range. Results use the less favourable end for "
            "'stronger fit' and the more favourable end for 'possible/ambitious'. Re-run with "
            "your official rank once results are declared.")
    seat_types = ["GENERAL"] + (["PWD"] if inp.pwd else [])

    rows = db.scalars(
        select(CutoffRecord).where(
            CutoffRecord.course_id == course.id,
            CutoffRecord.quota.in_(inp.quotas),
            CutoffRecord.seat_type.in_(seat_types),
            CutoffRecord.exam_year < inp.exam_year,
        )
    ).unique().all()

    # Group into comparable series: one authority + quota + category + seat type per college.
    series: dict[tuple, list[CutoffRecord]] = defaultdict(list)
    for r in rows:
        series[(r.college_id, r.authority_id, r.quota, r.category, r.seat_type)].append(r)

    excluded = defaultdict(int)
    open_rule_cache: dict[tuple, object] = {}
    candidates: dict[tuple, dict] = {}

    for (college_id, authority_id, quota, category, seat_type), recs in series.items():
        college = recs[0].college
        authority: CounsellingAuthority = recs[0].authority

        # --- eligibility filters
        if any(r.domicile_required for r in recs) and (
                not inp.domicile_state or inp.domicile_state.lower() != (authority.state or "").lower()):
            excluded["domicile_not_eligible"] += 1
            continue
        if category != student_cat:
            if category != "OPEN":
                continue  # another reserved category: never applicable
            latest_year = max(r.exam_year for r in recs)
            ck = (authority_id, latest_year, quota, college.is_demo)
            if ck not in open_rule_cache:
                open_rule_cache[ck] = _rule(db, authority_id, latest_year, quota, "open_category_accessible",
                                            demo=college.is_demo)
            if open_rule_cache[ck] is not True:
                if open_rule_cache[ck] is None:
                    excluded["open_seat_rule_unverified"] += 1
                continue

        # --- preference filters
        if inp.preferred_states and college.state not in inp.preferred_states:
            excluded["outside_preferred_states"] += 1
            continue
        if inp.institution_types and college.institution_type not in inp.institution_types:
            excluded["institution_type"] += 1
            continue

        basis = recs[0].rank_basis
        ranks = _student_ranks(inp, basis)
        if ranks is None:
            excluded["missing_rank_for_basis_" + basis.value] += 1
            continue
        rank_opt, rank_cons, estimated = ranks

        # Final-round closing rank per year, latest N years.
        by_year: dict[int, list[CutoffRecord]] = defaultdict(list)
        for r in recs:
            by_year[r.exam_year].append(r)
        years = sorted(by_year)[-inp.years_considered:]
        history = []
        for y in years:
            yr = sorted(by_year[y], key=lambda r: r.round_number)
            final, first = yr[-1], yr[0]
            history.append({
                "exam_year": y,
                "first_round": first.round_number, "first_round_closing_rank": first.closing_rank,
                "final_round": final.round_number, "final_round_name": final.round_name,
                "opening_rank": final.opening_rank, "closing_rank": final.closing_rank,
                "source_name": final.source_name, "source_url": final.source_url,
                "verification_status": final.verification_status.value,
                "last_verified_at": final.last_verified_at.isoformat() if final.last_verified_at else None,
            })
        closings = [h["closing_rank"] for h in history]
        fit = classify(rank_opt, rank_cons, closings)
        if fit is None:
            excluded["rank_beyond_historical_range"] += 1
            continue

        is_demo = college.is_demo or any(r.verification_status == VerificationStatus.demo for r in recs)
        conf, conf_reason = confidence(closings, estimated, is_demo)
        caveats = []
        if len(years) < inp.years_considered:
            caveats.append(f"Only {len(years)} of the requested {inp.years_considered} years have data.")
        if category != student_cat:
            caveats.append(f"Compared with {category} closing ranks (rule verified for {authority.code}).")
        if any(h["verification_status"] not in ("verified",) for h in history):
            caveats.append("Some cutoff records are not verified against the official source.")
        if is_demo:
            caveats.append("DEMO data: synthetic, for development only. Do not use for decisions.")

        cost = estimate_cost(db, college.id, inp.course_code, quota=quota)
        if inp.budget_max_annual and cost.available and cost.estimated_annual_total_inr > inp.budget_max_annual:
            excluded["over_budget"] += 1
            continue
        if inp.budget_max_annual and not cost.available:
            caveats.append("Fees unknown — cannot check against your budget.")
        hostel = db.scalars(select(HostelRecord).where(
            HostelRecord.college_id == college.id, HostelRecord.on_campus.is_(True))).first()
        if inp.hostel_required and hostel is None:
            caveats.append("No verified on-campus hostel information — contact the college.")

        toughest, lenient = min(closings), max(closings)
        rank_label = (f"AIR {rank_opt:,}–{rank_cons:,} (estimated)" if estimated and rank_opt != rank_cons
                      else f"{'State rank' if basis == RankBasis.STATE_RANK else 'AIR'} {rank_cons:,}"
                      + (" (estimated)" if estimated else " (official)"))
        explanation = (
            f"Your {rank_label} compared with {authority.code} {quota} {category}"
            f"{'' if seat_type == 'GENERAL' else ' ' + seat_type} final-round closing ranks of "
            f"{', '.join(f'{c:,}' for c in closings)} ({years[0]}–{years[-1]}). "
            + {STRONGER: f"Your rank is comfortably inside even the toughest year's closing rank ({toughest:,}).",
               POSSIBLE: f"Your rank falls within the range seen across years ({toughest:,}–{lenient:,}), so the outcome is uncertain.",
               AMBITIOUS: f"Your rank is slightly beyond the most lenient past closing rank ({lenient:,}); this would need a later-round or unusually lenient year."}[fit]
        )

        result = {
            "college_id": college.id, "college_code": college.code, "college_name": college.name,
            "city": college.city, "state": college.state, "institution_type": college.institution_type,
            "is_demo": is_demo,
            "course_code": inp.course_code,
            "counselling_authority": authority.code, "authority_name": authority.name,
            "quota": quota, "seat_type": seat_type, "category_used": category,
            "rank_basis": basis.value, "student_rank_display": rank_label, "rank_is_estimated": estimated,
            "historical_fit": fit, "confidence": conf, "confidence_reason": conf_reason,
            "years_considered": years, "history": history,
            "explanation": explanation, "caveats": caveats,
            "estimated_annual_cost_inr": cost.estimated_annual_total_inr if cost.available else None,
            "fee_academic_year": cost.academic_year,
            "hostel_on_campus": hostel is not None,
            "margin": round(1 - rank_cons / toughest, 3),
        }
        key = (college_id, authority_id, quota, seat_type)
        prev = candidates.get(key)
        if prev is None or (FIT_ORDER[fit], -result["margin"]) < (FIT_ORDER[prev["historical_fit"]], -prev["margin"]):
            candidates[key] = result

    results = sorted(candidates.values(), key=lambda r: (FIT_ORDER[r["historical_fit"]], -r["margin"]))
    groups = {label: [r for r in results if r["historical_fit"] == label] for label in FIT_ORDER}
    reason_text = {
        "domicile_not_eligible": "state-quota seats that need a domicile you have not entered (or another state's domicile)",
        "open_seat_rule_unverified": "OPEN-category rows skipped because the rule for your category is not verified",
        "outside_preferred_states": "outside your preferred states",
        "institution_type": "not matching your institution-type preference",
        "rank_beyond_historical_range": "past closing ranks well ahead of your rank",
        "over_budget": "estimated annual cost above your budget",
        "missing_rank_for_basis_STATE_RANK": "needs an official state rank you have not entered",
        "missing_rank_for_basis_AIR": "needs an AIR you have not entered",
    }
    return {
        "disclaimer": DISCLAIMER,
        "method": ("Historical cutoff matching: your rank vs final-round closing ranks for the same "
                   "authority, quota, category and seat type over recent years. No probabilities."),
        "input": {
            "course_code": inp.course_code, "exam_year": inp.exam_year, "rank_type": inp.rank_type.value,
            "category_used": student_cat, "domicile_state": inp.domicile_state, "quotas": inp.quotas,
            "years_considered": inp.years_considered,
        },
        "caveats": global_caveats,
        "counts": {k: len(v) for k, v in groups.items()},
        "groups": groups,
        "excluded": [{"reason": reason_text.get(k, k), "count": v} for k, v in excluded.items()],
    }
