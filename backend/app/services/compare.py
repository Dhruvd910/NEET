"""Side-by-side comparison of 2–5 colleges, explained against the student's own priorities.

There is no universal "best college": we only say which college leads on each criterion the
student chose, and only when the underlying data exists for every college compared.
"""
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import College, Facility, HostelRecord, NearbyPlace, OutcomeRecord, StudentReview
from app.services.catalog import latest_closing
from app.services.costs import estimate_cost

PRIORITIES = {
    "cost": "Lower estimated annual cost",
    "cutoff": "More accessible historical closing rank (AIQ OPEN, latest year)",
    "hostel": "On-campus hostel information available",
    "clinical": "Larger attached-hospital bed capacity",
    "ratings": "Higher average student rating",
    "transport": "Closer railway station / airport",
    "freshness": "More recently verified data",
}


class CompareError(ValueError):
    pass


def compare(db: Session, college_ids: list[int], priorities: list[str], course_code: str = "MBBS") -> dict:
    if not 2 <= len(set(college_ids)) <= 5:
        raise CompareError("Choose between 2 and 5 different colleges.")
    unknown = [p for p in priorities if p not in PRIORITIES]
    if unknown:
        raise CompareError(f"Unknown priorities: {', '.join(unknown)}")

    rows = []
    for cid in dict.fromkeys(college_ids):
        c = db.get(College, cid)
        if c is None:
            raise CompareError(f"College {cid} not found.")
        cost = estimate_cost(db, c.id, course_code)
        closings = latest_closing(db, c.id, course_code)
        aiq_open = next((x for x in closings if x["quota"] == "AIQ" and x["category"] == "OPEN"
                         and x["seat_type"] == "GENERAL"), None)
        hostel = db.scalars(select(HostelRecord).where(HostelRecord.college_id == c.id,
                                                       HostelRecord.on_campus.is_(True))).first()
        beds = db.scalars(select(Facility).where(Facility.college_id == c.id,
                                                 Facility.category == "clinical", Facility.unit == "beds")).first()
        stipend = db.scalars(select(OutcomeRecord).where(OutcomeRecord.college_id == c.id,
                                                         OutcomeRecord.metric == "internship_stipend_monthly")).first()
        reviews = db.scalars(select(StudentReview.rating).where(StudentReview.college_id == c.id,
                                                                StudentReview.status == "approved")).all()
        places = db.scalars(select(NearbyPlace).where(NearbyPlace.college_id == c.id)).all()
        nearest = lambda kind: min((p.distance_km for p in places if p.kind == kind and p.distance_km is not None),
                                   default=None)
        pg = [p for p in places if p.kind == "pg"]
        verified_dates = [d for d in (c.last_verified_at, ) if d]
        rows.append({
            "id": c.id, "name": c.name, "city": c.city, "state": c.state, "institution_type": c.institution_type,
            "is_demo": c.is_demo, "recognition_status": c.recognition_status,
            "recognition_year": c.recognition_year,
            "intake": {cc.academic_year: cc.approved_intake for cc in c.courses if cc.course.code == course_code},
            "counselling_routes": sorted({f"{x['authority']} {x['quota']}" for x in closings}),
            "aiq_open_closing": aiq_open,
            "annual_cost_inr": cost.estimated_annual_total_inr if cost.available else None,
            "full_course_cost_inr": cost.estimated_full_course_inr if cost.available else None,
            "fee_year": cost.academic_year, "hostel_mess_annual_inr": cost.annual_hostel_mess_inr if cost.available else None,
            "hostel_on_campus": hostel is not None,
            "hospital_beds": beds.numeric_value if beds else None,
            "internship_stipend_monthly_inr": stipend.value_numeric if stipend else None,
            "avg_rating": round(mean(reviews), 1) if reviews else None, "review_count": len(reviews),
            "nearest_railway_km": nearest("railway"), "nearest_airport_km": nearest("airport"),
            "nearby_pg_count": len(pg),
            "last_verified_at": max(verified_dates).isoformat() if verified_dates else None,
            "data_status": c.verification_status.value,
            "completeness": sum(v is not None for v in (cost.available or None, aiq_open, hostel, beds, stipend,
                                                        reviews or None)) / 6,
        })

    insights = []
    def leader(key, label, lower_is_better=False, fmt=str):
        vals = [(r[key], r["name"]) for r in rows if r[key] is not None]
        if len(vals) < len(rows):
            missing = [r["name"] for r in rows if r[key] is None]
            insights.append(f"{label}: can't compare fairly — data missing for {', '.join(missing)}.")
            return
        best = (min if lower_is_better else max)(vals, key=lambda v: v[0])
        insights.append(f"{label}: {best[1]} ({fmt(best[0])}).")

    for p in priorities:
        if p == "cost":
            leader("annual_cost_inr", PRIORITIES[p], True, lambda v: f"≈ ₹{v:,} per year")
        elif p == "cutoff":
            for r in rows:
                r["_aiq_close"] = r["aiq_open_closing"]["closing_rank"] if r["aiq_open_closing"] else None
            leader("_aiq_close", PRIORITIES[p], False, lambda v: f"closing AIR {v:,}")
        elif p == "hostel":
            have = [r["name"] for r in rows if r["hostel_on_campus"]]
            insights.append(f"{PRIORITIES[p]}: {', '.join(have) if have else 'none of these have hostel data'}. "
                            "Check each record's verification status on the college page.")
        elif p == "clinical":
            leader("hospital_beds", PRIORITIES[p], False, lambda v: f"{int(v):,} beds")
        elif p == "ratings":
            leader("avg_rating", PRIORITIES[p], False, lambda v: f"{v}/5 from student reviews")
        elif p == "transport":
            leader("nearest_railway_km", PRIORITIES[p], True, lambda v: f"{v} km to railway")
        elif p == "freshness":
            leader("last_verified_at", PRIORITIES[p], False, lambda v: v[:10])
    for r in rows:
        r.pop("_aiq_close", None)

    return {
        "course_code": course_code, "colleges": rows, "priorities": [PRIORITIES[p] for p in priorities],
        "insights": insights,
        "note": ("Comparison reflects only the criteria you selected and the data available. It does not "
                 "name a universal 'best' college. Cutoffs are historical and do not guarantee admission."),
        "any_demo": any(r["is_demo"] for r in rows),
    }
