"""College catalog read models shared by the REST API and the assistant tools."""
from statistics import mean

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    College, CollegeAlias, CollegeCourse, CutoffRecord, Facility, HostelRecord, NearbyPlace,
    OutcomeRecord, SeatMatrix, StudentReview,
)
from app.services.costs import estimate_cost
from app.services.normalize import normalize_name
from app.services.places import KIND_CATEGORY, walk_minutes


def provenance(r) -> dict:
    return {
        "source_name": r.source_name, "source_url": r.source_url,
        "publication_date": r.publication_date.isoformat() if r.publication_date else None,
        "collected_at": r.collected_at.isoformat() if r.collected_at else None,
        "last_verified_at": r.last_verified_at.isoformat() if r.last_verified_at else None,
        "verification_status": r.verification_status.value,
    }


def search_colleges(db: Session, *, q: str | None = None, state: str | None = None, course: str | None = None,
                    institution_type: str | None = None, page: int = 1, page_size: int = 20) -> dict:
    stmt = select(College)
    if q:
        key = normalize_name(q)
        alias_ids = select(CollegeAlias.college_id).where(CollegeAlias.normalized.like(f"%{key}%"))
        stmt = stmt.where(or_(College.name.ilike(f"%{q}%"), College.city.ilike(f"%{q}%"), College.id.in_(alias_ids)))
    if state:
        stmt = stmt.where(College.state == state)
    if institution_type:
        stmt = stmt.where(College.institution_type == institution_type)
    if course:
        from app.models import Course
        stmt = stmt.where(College.id.in_(
            select(CollegeCourse.college_id).join(Course).where(Course.code == course)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(College.state, College.name).offset((page - 1) * page_size).limit(page_size)).unique().all()
    return {"total": total, "page": page, "page_size": page_size,
            "items": [college_card(db, c, course or "MBBS") for c in rows]}


def college_card(db: Session, c: College, course_code: str = "MBBS") -> dict:
    cost = estimate_cost(db, c.id, course_code)
    hostel = db.scalars(select(HostelRecord).where(HostelRecord.college_id == c.id,
                                                   HostelRecord.on_campus.is_(True))).first()
    return {
        "id": c.id, "code": c.code, "name": c.name, "city": c.city, "state": c.state,
        "institution_type": c.institution_type, "is_demo": c.is_demo,
        "courses": sorted({cc.course.code for cc in c.courses}),
        "fee_summary": ({"annual_total_inr": cost.estimated_annual_total_inr, "academic_year": cost.academic_year,
                         "verified": all(s == "verified" for s in cost.verification_statuses)}
                        if cost.available else None),
        "hostel_summary": ({"on_campus": True, "verification_status": hostel.verification_status.value}
                           if hostel else None),
        "verification_status": c.verification_status.value,
    }


def college_detail(db: Session, c: College) -> dict:
    cutoffs = db.scalars(select(CutoffRecord).where(CutoffRecord.college_id == c.id)
                         .order_by(CutoffRecord.exam_year.desc(), CutoffRecord.authority_id,
                                   CutoffRecord.quota, CutoffRecord.category, CutoffRecord.round_number)).unique().all()
    seats = db.scalars(select(SeatMatrix).where(SeatMatrix.college_id == c.id)).all()
    hostels = db.scalars(select(HostelRecord).where(HostelRecord.college_id == c.id)).all()
    facilities = db.scalars(select(Facility).where(Facility.college_id == c.id)).all()
    outcomes = db.scalars(select(OutcomeRecord).where(OutcomeRecord.college_id == c.id)).all()
    nearby = db.scalars(select(NearbyPlace).where(NearbyPlace.college_id == c.id)
                        .order_by(NearbyPlace.kind, NearbyPlace.distance_km)).all()
    reviews = db.scalars(select(StudentReview).where(StudentReview.college_id == c.id,
                                                     StudentReview.status == "approved")).all()
    authorities = sorted({r.authority.code for r in cutoffs})
    courses = {}
    for cc in c.courses:
        courses.setdefault(cc.course.code, []).append({
            "course": cc.course.name, "academic_year": cc.academic_year, "approved_intake": cc.approved_intake,
            "duration_years": cc.course.duration_years, "duration_note": cc.course.duration_note,
            **provenance(cc)})
    costs = {code: estimate_cost(db, c.id, code).to_dict() for code in courses}

    return {
        "overview": {
            "id": c.id, "code": c.code, "name": c.name, "aliases": [a.alias for a in c.aliases],
            "website": c.website, "address": c.address, "city": c.city, "state": c.state,
            "latitude": None if c.is_demo else c.latitude, "longitude": None if c.is_demo else c.longitude,
            "institution_type": c.institution_type,
            "university": c.university.name if c.university else None,
            "established_year": c.established_year, "recognition_status": c.recognition_status,
            "recognition_year": c.recognition_year, "recognition_note": c.recognition_note,
            "website_source": c.website_source, "location_source": c.location_source,
            "pincode": c.pincode, "contact_email": c.contact_email, "contact_phone": c.contact_phone,
            "is_demo": c.is_demo, "courses": courses, **provenance(c),
        },
        "admission": {
            "entrance_exam": "NEET-UG",
            "counselling_authorities": authorities,
            "cutoffs": [{
                "course": r.course.code, "authority": r.authority.code, "exam_year": r.exam_year,
                "round": r.round_number, "round_name": r.round_name, "quota": r.quota, "category": r.category,
                "seat_type": r.seat_type, "rank_basis": r.rank_basis.value, "domicile_required": r.domicile_required,
                "opening_rank": r.opening_rank, "closing_rank": r.closing_rank, **provenance(r)} for r in cutoffs],
            "seat_matrix": [{"exam_year": s.exam_year, "round": s.round_number, "quota": s.quota,
                             "category": s.category, "seat_type": s.seat_type, "seats": s.seats, **provenance(s)}
                            for s in seats],
        },
        "costs": costs,
        "hostels": [{
            "on_campus": h.on_campus, "provider_name": h.provider_name, "gender": h.gender,
            "hostel_count": h.hostel_count, "capacity": h.capacity, "room_types": h.room_types,
            "facilities": h.facilities, "rules_note": h.rules_note, "rent_min_inr": h.rent_min_inr,
            "rent_max_inr": h.rent_max_inr, "rent_period": h.rent_period, "distance_km": h.distance_km,
            "availability_note": h.availability_note or "Live availability is not tracked — contact the provider.",
            **provenance(h)} for h in hostels],
        "facilities": [{"category": f.category, "name": f.name, "details": f.details,
                        "numeric_value": f.numeric_value, "unit": f.unit, **provenance(f)} for f in facilities],
        "outcomes": [{"metric": o.metric, "value_text": o.value_text, "value_numeric": o.value_numeric,
                      "year": o.year, "comparable": o.comparable, **provenance(o)} for o in outcomes],
        "nearby": [{"kind": n.kind, "category": KIND_CATEGORY.get(n.kind, "Other"), "name": n.name,
                    "distance_km": n.distance_km, "walk_minutes": walk_minutes(n.distance_km), "route_url": n.route_url,
                    # Demo colleges have fictional locations: never put their places on a real map.
                    "latitude": None if n.is_demo else n.latitude, "longitude": None if n.is_demo else n.longitude,
                    "price_range": n.price_range, "provider": n.provider, "attribution": n.attribution,
                    "is_demo": n.is_demo,
                    "last_checked_at": n.last_checked_at.isoformat() if n.last_checked_at else None}
                   for n in nearby],
        "reviews": {
            "label": "Student-reported experiences (moderated). Not verified facts.",
            "count": len(reviews),
            "average_rating": round(mean(r.rating for r in reviews), 1) if reviews else None,
            "items": [{"rating": r.rating, "aspect_ratings": r.aspect_ratings, "body": r.body,
                       "is_demo": r.is_demo, "created_at": r.created_at.isoformat()} for r in reviews[:20]],
        },
    }


def latest_closing(db: Session, college_id: int, course_code: str = "MBBS") -> list[dict]:
    """Most recent final-round closing ranks per authority/quota/category (for comparison)."""
    from app.models import Course
    rows = db.scalars(select(CutoffRecord).join(Course).where(
        CutoffRecord.college_id == college_id, Course.code == course_code)).unique().all()
    latest: dict[tuple, CutoffRecord] = {}
    for r in rows:
        k = (r.authority.code, r.quota, r.category, r.seat_type)
        cur = latest.get(k)
        if cur is None or (r.exam_year, r.round_number) > (cur.exam_year, cur.round_number):
            latest[k] = r
    return [{"authority": k[0], "quota": k[1], "category": k[2], "seat_type": k[3],
             "exam_year": r.exam_year, "round": r.round_number, "closing_rank": r.closing_rank,
             "rank_basis": r.rank_basis.value, "verification_status": r.verification_status.value}
            for k, r in sorted(latest.items())]
