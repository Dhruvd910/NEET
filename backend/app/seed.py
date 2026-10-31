"""Seed reference data and clearly-labelled DEMO data.

    python -m app.seed            # reference data + demo catalog + demo accounts
    python -m app.seed --no-demo  # reference data only (production)

Reference data = courses, counselling authorities (names & official websites), information-hub
articles marked `pending_review` with their official source links.

DEMO data = fictional colleges ("(DEMO)" in the name, is_demo=True, verification_status=demo)
with synthetic cutoffs, fees and hostels generated from a fixed random seed. It exists only to
develop and test the product and must never be shown as real.
"""
import argparse
import os
import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    College, CollegeAlias, CollegeCourse, CounsellingAuthority, Course, CutoffRecord, DataSource,
    EligibilityRule, ExamProfile, Facility, FeeRecord, HostelRecord, InfoArticle, MockTest,
    MockTestSubjectScore, NearbyPlace, OutcomeRecord, RankBasis, RankType, Role, StudentProfile,
    StudentReview, University, User, VerificationStatus,
)
from app.practice_seed import seed_sample_questions, seed_syllabus
from app.security import hash_password
from app.services.normalize import normalize_name

DEMO = VerificationStatus.demo
DEMO_SOURCE = "DEMO — synthetic development data (not real)"
PENDING = VerificationStatus.pending_review

COURSES = [
    ("MBBS", "Bachelor of Medicine and Bachelor of Surgery", 5.5, "4.5 years academic + 1 year compulsory rotating internship", "NEET-UG"),
    ("BDS", "Bachelor of Dental Surgery", 5.0, "4 years academic + 1 year internship", "NEET-UG"),
    ("BAMS", "Bachelor of Ayurvedic Medicine and Surgery", 5.5, "Includes internship", "NEET-UG"),
    ("BHMS", "Bachelor of Homoeopathic Medicine and Surgery", 5.5, "Includes internship", "NEET-UG"),
]

AUTHORITIES = [
    ("MCC", "Medical Counselling Committee (DGHS, Govt. of India)", "central", None, "https://mcc.nic.in",
     ["AIQ", "DEEMED", "CENTRAL", "AIIMS", "JIPMER", "ESIC", "AFMS"]),
    ("KEA", "Karnataka Examinations Authority", "state", "Karnataka", "https://cetonline.karnataka.gov.in/kea/",
     ["STATE", "MANAGEMENT", "NRI"]),
    ("MH-CET", "State CET Cell, Maharashtra", "state", "Maharashtra", "https://cetcell.mahacet.org",
     ["STATE", "MANAGEMENT", "NRI"]),
    ("TN-DME", "Selection Committee, Directorate of Medical Education, Tamil Nadu", "state", "Tamil Nadu",
     "https://tnmedicalselection.net", ["STATE", "MANAGEMENT", "NRI"]),
]

DATA_SOURCES = [
    ("NTA", "National Testing Agency — NEET-UG", "official_portal", "https://neet.nta.nic.in", False),
    ("NMC", "National Medical Commission", "official_portal", "https://www.nmc.org.in", False),
    ("MCC", "Medical Counselling Committee", "official_portal", "https://mcc.nic.in", False),
    ("OSM", "OpenStreetMap (via Overpass API)", "licensed_api", "https://www.openstreetmap.org", True),
    ("DEMO", DEMO_SOURCE, "demo", None, True),
]

NTA = "https://neet.nta.nic.in"
INFO = [
    ("neet", "overview", "What is NEET-UG?", NTA,
     "NEET-UG (National Eligibility cum Entrance Test – Undergraduate) is conducted by the National Testing Agency (NTA). "
     "It is the entrance test for admission to MBBS, BDS and AYUSH courses (and some other courses) in India.\n\n"
     "The authoritative source for each year's exam is the NTA Information Bulletin for that year."),
    ("neet", "pattern", "Exam pattern and marking scheme", NTA,
     "The paper is a pen-and-paper, multiple-choice test in Physics, Chemistry and Biology (Botany & Zoology). "
     "In recent years the marking has been +4 for a correct answer and −1 for an incorrect one, with no marks for "
     "unattempted questions.\n\nThe number of questions, sections, duration and any optional-question scheme have "
     "changed between years. Check the current Information Bulletin before relying on any of these details."),
    ("neet", "syllabus", "Syllabus and subjects", "https://www.nmc.org.in",
     "The NEET-UG syllabus is notified by the National Medical Commission and covers Physics, Chemistry and Biology "
     "from classes 11 and 12. Download the syllabus PDF for your exam year from NMC/NTA — topics are revised from "
     "time to time."),
    ("neet", "eligibility", "Eligibility criteria", NTA,
     "Eligibility covers age, nationality, qualifying examination (class 12 with Physics, Chemistry, Biology/"
     "Biotechnology and English) and minimum marks in PCB that differ by category. Rules change and have exceptions; "
     "confirm every criterion in the current Information Bulletin. This page is pending verification."),
    ("neet", "application", "Application, correction window, admit card and results", NTA,
     "NTA announces the application window, correction window, city intimation slip, admit card release, exam date, "
     "provisional answer key and result through public notices on its website. Dates change every year, so this "
     "platform does not hard-code them — see the Important Notices list for verified notices with their dates."),
    ("neet", "qualifying", "Qualifying percentile and ranks", NTA,
     "To qualify, candidates must reach a minimum percentile that depends on category. The qualifying cutoff scores "
     "are published with the result. Qualifying NEET makes you eligible to take part in counselling — it does not "
     "guarantee a seat. Your All India Rank (AIR) is published by NTA; state merit lists/ranks are published by state "
     "counselling authorities."),
    ("counselling", "overview", "How medical counselling works", "https://mcc.nic.in",
     "Seats are allotted through separate counselling routes:\n\n"
     "• All India Quota (AIQ): 15% of seats in government medical colleges, plus deemed and central universities, "
     "AIIMS, JIPMER and others — run by the Medical Counselling Committee (MCC).\n"
     "• State quota: the remaining government seats plus private-college seats — run by each state's counselling "
     "authority, usually requiring domicile.\n\n"
     "Each route has its own registration, fees, choice filling, rounds and rules. Cutoffs from one route cannot be "
     "compared with another."),
    ("counselling", "choice-filling", "Choice filling, locking and allotment", "https://mcc.nic.in",
     "During choice filling you list colleges in order of preference. Allotment generally goes through candidates in "
     "merit order and gives each the highest choice still available for their eligibility. Lock your choices before "
     "the deadline. Rules on upgrades, free exit, resignation and forfeiture of security deposits differ by authority "
     "and year — read the current counselling scheme before every round."),
    ("counselling", "documents", "Document checklist (general)", "https://mcc.nic.in",
     "Commonly required: NEET admit card and rank letter/scorecard, class 10 certificate (date of birth), class 12 "
     "marksheet and certificate, ID proof, passport-size photographs, category certificate (if applicable, in the "
     "prescribed format), PwD certificate (if applicable), domicile certificate for state quota, and the provisional "
     "allotment letter. The official counselling notice is the final authority on required documents and formats."),
    ("careers", "bds", "BDS (Dental Surgery)", "https://dciindia.gov.in",
     "Admission through NEET-UG counselling (often the same counselling as MBBS). About 5 years including internship. "
     "Careers: dental practice, MDS specialisation, public health, research, academia."),
    ("careers", "ayush", "AYUSH (BAMS, BHMS, BUMS, BSMS)", "https://aaccc.gov.in",
     "Admission through NEET-UG; all-India AYUSH counselling is run by AACCC and state seats by state authorities. "
     "About 5.5 years including internship. Verify the current eligibility and counselling rules for your year."),
    ("careers", "veterinary", "Veterinary Science (B.V.Sc & A.H.)", "https://vci.dahd.gov.in",
     "A share of seats is filled through NEET-UG via the Veterinary Council of India; many state seats use state "
     "processes. About 5.5 years including internship. Rules differ by state — verify before applying."),
    ("careers", "pharmacy", "Pharmacy (B.Pharm / Pharm.D)", "https://www.pci.nic.in",
     "Usually admitted through state entrance tests or CUET/institution tests, not NEET counselling. B.Pharm is 4 "
     "years; Pharm.D is 6 years. Careers: industry, hospital/clinical pharmacy, regulatory affairs, research."),
    ("careers", "nursing", "Nursing (B.Sc Nursing)", "https://www.indiannursingcouncil.org",
     "Admission routes vary: some institutions/states use NEET-UG scores, others run their own tests. 4 years. "
     "Check each institution's current admission notice."),
    ("careers", "allied", "Allied health sciences", None,
     "Physiotherapy, medical lab technology, radiology/imaging, optometry, anaesthesia & OT technology and more. "
     "Entrance routes vary by state and institution. Typically 3–4.5 years."),
    ("careers", "biosciences", "Biotechnology, life sciences and biomedical research", None,
     "B.Sc/B.Tech/BS-MS routes via CUET, JEE, IISER aptitude test or institution exams. Leads to research, industry "
     "and higher studies (M.Sc, PhD)."),
]

# (code suffix, type, state, authority, base AIQ OPEN closing AIR, courses, hostel?)
DEMO_COLLEGES = [
    ("KA-GOV-A", "government", "Karnataka", "KEA", 3200, ["MBBS"], True),
    ("KA-GOV-B", "government", "Karnataka", "KEA", 9800, ["MBBS", "BDS"], True),
    ("KA-PVT-C", "private", "Karnataka", "KEA", 38000, ["MBBS", "BDS"], True),
    ("KA-DMD-D", "deemed", "Karnataka", "MCC", 95000, ["MBBS", "BDS"], True),
    ("MH-GOV-A", "government", "Maharashtra", "MH-CET", 2100, ["MBBS"], True),
    ("MH-GOV-B", "government", "Maharashtra", "MH-CET", 14500, ["MBBS"], False),
    ("MH-PVT-C", "private", "Maharashtra", "MH-CET", 52000, ["MBBS", "BDS"], True),
    ("TN-GOV-A", "government", "Tamil Nadu", "TN-DME", 4500, ["MBBS", "BDS"], True),
    ("TN-GOV-B", "government", "Tamil Nadu", "TN-DME", 21000, ["MBBS"], True),
    ("TN-PVT-C", "private", "Tamil Nadu", "TN-DME", 61000, ["MBBS"], True),
    ("DL-CEN-A", "central", "Delhi", "MCC", 900, ["MBBS"], True),
    ("KA-DMD-E", "deemed", "Karnataka", "MCC", 140000, ["MBBS"], False),
]
GREEK = {"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta", "E": "Epsilon"}
CATEGORY_MULT = {"OPEN": 1.0, "EWS": 1.12, "OBC": 1.18, "SC": 5.5, "ST": 9.0}
YEARS = [2023, 2024, 2025]


def get_or_create(db: Session, model, defaults=None, **keys):
    obj = db.scalar(select(model).filter_by(**keys))
    if obj is None:
        obj = model(**keys, **(defaults or {}))
        db.add(obj)
        db.flush()
    return obj


def seed_reference(db: Session):
    for code, name, dur, note, exam in COURSES:
        get_or_create(db, Course, code=code, defaults=dict(name=name, duration_years=dur, duration_note=note, entrance_exam=exam))
    for code, name, level, state, web, quotas in AUTHORITIES:
        get_or_create(db, CounsellingAuthority, code=code,
                      defaults=dict(name=name, level=level, state=state, website=web, quotas=quotas))
    for code, name, kind, url, permitted in DATA_SOURCES:
        # Real sources start "unreviewed": an admin records the terms-of-use review before any import.
        get_or_create(db, DataSource, code=code, defaults=dict(
            name=name, kind=kind, base_url=url, automated_access_permitted=permitted,
            usage_status="allowed" if kind == "demo" else "unreviewed",
            terms_url="https://osmfoundation.org/wiki/Licence" if code == "OSM" else None,
            attribution_text="© OpenStreetMap contributors" if code == "OSM" else None,
            terms_note="Check terms of use before any automated access." if kind != "demo" else "Synthetic."))
    for a_code, name, _level, _state, web, _quotas in AUTHORITIES:
        if a_code != "MCC":
            get_or_create(db, DataSource, code=a_code, defaults=dict(
                name=name, kind="official_portal", base_url=web, usage_status="unreviewed",
                terms_note="Check terms of use before any automated access."))
    seed_syllabus(db)
    for i, (section, slug, title, url, body) in enumerate(INFO):
        get_or_create(db, InfoArticle, slug=f"{section}-{slug}", defaults=dict(
            section=section, title=title, body=body, sort_order=i, source_name="Platform editorial summary of official sources",
            source_url=url, verification_status=PENDING))
    db.commit()


def seed_demo(db: Session):
    seed_sample_questions(db)
    _seed_demo_catalog(db)


def _seed_demo_catalog(db: Session):
    rng = random.Random(2024)
    courses = {c.code: c for c in db.scalars(select(Course))}
    auth = {a.code: a for a in db.scalars(select(CounsellingAuthority))}
    uni = get_or_create(db, University, name="Demo Health Sciences University (DEMO)", defaults=dict(state=None))
    now = datetime.now(timezone.utc)
    prov = dict(source_name=DEMO_SOURCE, source_url=None, verification_status=DEMO)

    for suffix, itype, state, state_auth, base, course_codes, has_hostel in DEMO_COLLEGES:
        greek = GREEK[suffix[-1]]
        type_word = {"government": "Government Medical College", "private": "Medical College & Hospital",
                     "deemed": "Institute of Medical Sciences (Deemed)", "central": "Central Institute of Medical Sciences"}[itype]
        name = f"{greek} {type_word}, {state} (DEMO)"
        if db.scalar(select(College).where(College.code == f"DEMO-{suffix}")):
            continue
        c = College(code=f"DEMO-{suffix}", name=name, state=state, city=f"{greek}pur (fictional)",
                    address="Fictional address — demo data", institution_type=itype, university_id=uni.id,
                    established_year=rng.randint(1950, 2015), website=None,
                    recognition_status="DEMO — not a real recognition status", recognition_year="2025-26",
                    is_demo=True, **prov)
        c.aliases = [CollegeAlias(alias=f"{greek} {itype[:3].upper()} MC {state}",
                                  normalized=normalize_name(f"{greek} {itype[:3].upper()} MC {state} demo"))]
        db.add(c)
        db.flush()

        for cc in course_codes:
            db.add(CollegeCourse(college_id=c.id, course_id=courses[cc].id, academic_year="2025-26",
                                 approved_intake=rng.choice([100, 150, 200, 250]) if cc == "MBBS" else rng.choice([50, 100]), **prov))

        # ---- cutoffs: one series per route, category and year; rounds get progressively more lenient
        routes = []
        if itype in ("government",):
            routes += [("MCC", "AIQ", RankBasis.AIR, False, 1.0),
                       (state_auth, "STATE", RankBasis.STATE_RANK if state_auth == "KEA" else RankBasis.AIR, True, 1.35)]
        elif itype == "private":
            routes += [(state_auth, "STATE", RankBasis.STATE_RANK if state_auth == "KEA" else RankBasis.AIR, True, 1.0),
                       (state_auth, "MANAGEMENT", RankBasis.AIR, False, 3.5)]
        elif itype == "deemed":
            routes += [("MCC", "DEEMED", RankBasis.AIR, False, 1.0)]
        elif itype == "central":
            routes += [("MCC", "CENTRAL", RankBasis.AIR, False, 1.0), ("MCC", "AIQ", RankBasis.AIR, False, 1.1)]

        for cc in course_codes:
            course_mult = 1.0 if cc == "MBBS" else 4.0
            for a_code, quota, basis, dom, route_mult in routes:
                cats = ["OPEN"] if quota in ("MANAGEMENT", "DEEMED") else list(CATEGORY_MULT)
                basis_mult = 0.06 if basis == RankBasis.STATE_RANK else 1.0  # state ranks are much smaller numbers
                rounds = 3 if a_code == "MCC" else 2
                for cat in cats:
                    for y in YEARS:
                        drift = rng.uniform(0.85, 1.18)
                        final = max(10, int(base * course_mult * route_mult * CATEGORY_MULT[cat] * basis_mult * drift))
                        for rnd in range(1, rounds + 1):
                            closing = int(final * (0.82 + 0.18 * rnd / rounds))
                            db.add(CutoffRecord(
                                college_id=c.id, course_id=courses[cc].id, authority_id=auth[a_code].id, exam_year=y,
                                round_number=rnd, round_name=f"Round {rnd}", quota=quota, category=cat,
                                seat_type="GENERAL", domicile_required=dom, rank_basis=basis,
                                opening_rank=max(1, int(closing * rng.uniform(0.15, 0.4))), closing_rank=closing,
                                publication_date=date(y, 9, 1), **prov))

        # ---- rules (demo): whether reserved-category students are compared with OPEN rows
        for a_code, quota, *_ in routes:
            for y in YEARS:
                get_or_create(db, EligibilityRule, authority_id=auth[a_code].id, exam_year=y, quota=quota,
                              rule_key="open_category_accessible",
                              defaults=dict(rule_value={"value": True},
                                            description="DEMO rule: open seats are compared for all categories.", **prov))

        # ---- fees (single academic year, demo)
        tuition = {"government": rng.randint(15, 80) * 1000, "central": rng.randint(5, 20) * 1000,
                   "private": rng.randint(8, 16) * 100000, "deemed": rng.randint(18, 28) * 100000}[itype]
        fees = [("tuition", tuition, "annual", True, False), ("admission", rng.randint(5, 25) * 1000, "one_time", True, False),
                ("exam", rng.randint(3, 10) * 1000, "annual", True, False),
                ("security_deposit", rng.randint(10, 50) * 1000, "one_time", True, True),
                ("other", rng.randint(5, 30) * 1000, "annual", False, False)]
        if has_hostel:
            fees += [("hostel", rng.randint(20, 120) * 1000, "annual", False, False),
                     ("mess", rng.randint(3, 5) * 1000, "monthly", False, False)]
        for ftype, amt, period, mand, refundable in fees:
            db.add(FeeRecord(college_id=c.id, course_id=courses["MBBS"].id if "MBBS" in course_codes else None,
                             academic_year="2025-26", quota="ALL", fee_type=ftype, amount_inr=amt, period=period,
                             mandatory=mand, refundable=refundable, **prov))

        if has_hostel:
            for g in ("boys", "girls"):
                db.add(HostelRecord(college_id=c.id, on_campus=True, gender=g, hostel_count=rng.randint(1, 4),
                                    capacity=rng.randint(150, 600), room_types=["double", "triple"],
                                    facilities=["Wi-Fi", "mess", "laundry", "24x7 security"], **prov))
        db.add(HostelRecord(college_id=c.id, on_campus=False, provider_name="Demo PG near campus (fictional)",
                            gender="all", rent_min_inr=rng.randint(5, 9) * 1000, rent_max_inr=rng.randint(10, 18) * 1000,
                            rent_period="monthly", distance_km=round(rng.uniform(0.3, 2.5), 1),
                            availability_note="Demo listing. Contact the provider for live availability.", **prov))

        db.add(Facility(college_id=c.id, category="clinical", name="Attached teaching hospital",
                        details="DEMO hospital", numeric_value=rng.randint(500, 2000), unit="beds", **prov))
        db.add(Facility(college_id=c.id, category="academic", name="Central library",
                        details="DEMO: reading hall, e-journals", **prov))
        db.add(Facility(college_id=c.id, category="research", name="Research cell",
                        details="DEMO: ICMR short-term studentship guidance", **prov))
        db.add(OutcomeRecord(college_id=c.id, metric="internship_stipend_monthly",
                             value_numeric=rng.randint(15, 35) * 1000, year="2025-26", comparable=False, **prov))
        db.add(OutcomeRecord(college_id=c.id, metric="pg_pathway_note",
                             value_text="DEMO: no verified NEET-PG outcome statistics are available.", comparable=False, **prov))

        for kind, nm, lo, hi in (("bus_stop", "Demo Bus Stand", 0.1, 0.8), ("railway", "Demo Junction", 1, 12),
                                 ("airport", "Demo Airport", 8, 45), ("pharmacy", "Demo Pharmacy", 0.1, 1),
                                 ("grocery", "Demo Market", 0.2, 1.5), ("restaurant", "Demo Canteen & Mess", 0.1, 1),
                                 ("atm", "Demo Bank ATM", 0.1, 1), ("pg", "Demo PG (fictional)", 0.3, 2.5)):
            db.add(NearbyPlace(college_id=c.id, kind=kind, name=nm, distance_km=round(rng.uniform(lo, hi), 1),
                               provider="demo", is_demo=True, last_checked_at=now - timedelta(days=rng.randint(1, 60)),
                               price_range="₹6k–15k/month" if kind == "pg" else None))
        for _ in range(rng.randint(0, 3)):
            db.add(StudentReview(college_id=c.id, rating=rng.randint(3, 5), status="approved", is_demo=True,
                                 aspect_ratings={"academics": rng.randint(3, 5), "hostel": rng.randint(2, 5)},
                                 body="DEMO review: synthetic text used to develop the reviews section. Not a real student's opinion."))
    db.commit()


def seed_demo_accounts(db: Session):
    """Demo accounts on the *.test domain; password comes from SEED_DEMO_PASSWORD (see .env.example)."""
    password = os.environ.get("SEED_DEMO_PASSWORD", "demo-password-123")
    admin = get_or_create(db, User, email="admin@demo.test",
                          defaults=dict(password_hash=hash_password(password), role=Role.admin))
    student = get_or_create(db, User, email="student@demo.test",
                            defaults=dict(password_hash=hash_password(password), role=Role.student,
                                          is_minor=True, guardian_consent=True,
                                          guardian_email="guardian@demo.test"))
    # Demo only: guardian consent is pre-confirmed so the demo account is usable.
    student.guardian_consent_status = "verified"
    student.guardian_email = student.guardian_email or "guardian@demo.test"
    if db.scalar(select(StudentProfile).where(StudentProfile.user_id == student.id)) is None:
        db.add(StudentProfile(user_id=student.id, display_name="Demo Student", current_class="12",
                              academic_year="2025-26", state="Karnataka", domicile_state="Karnataka",
                              category="OBC", pwd=False, preferred_course="MBBS",
                              preferred_states=[], institution_preferences=[], budget_max_annual=None,
                              hostel_required=True))
        db.add(ExamProfile(user_id=student.id, exam_year=2026, has_taken=True, air=11500, state_rank=650,
                           rank_type=RankType.official, score=None))
        rng = random.Random(7)
        for i in range(6):
            d = date(2025, 11, 1) + timedelta(days=21 * i)
            p, c, b = rng.randint(80, 140), rng.randint(90, 150), rng.randint(250, 330)
            t = MockTest(user_id=student.id, name=f"Demo full test {i + 1}", provider="Demo provider", test_date=d,
                         total_score=p + c + b, max_score=720)
            t.subjects = [MockTestSubjectScore(subject="Physics", score=p, max_score=180,
                                               weak_topics=["Rotational motion"] if i % 2 else ["Electrostatics"]),
                          MockTestSubjectScore(subject="Chemistry", score=c, max_score=180, weak_topics=["Organic named reactions"]),
                          MockTestSubjectScore(subject="Biology", score=b, max_score=360, weak_topics=[])]
            db.add(t)
    db.commit()
    return admin, student


def remove_demo(db: Session) -> dict:
    """Delete every demo record (colleges and everything attached to them, demo rules, demo accounts).

    Run this before loading real data into a database that was seeded with demo data.
    """
    from sqlalchemy import delete, update

    from app.models import Question
    counts = {
        "eligibility_rules": db.execute(delete(EligibilityRule).where(
            EligibilityRule.verification_status == VerificationStatus.demo)).rowcount,
        "colleges": db.execute(delete(College).where(College.is_demo.is_(True))).rowcount,  # FK cascades
        "accounts": db.execute(delete(User).where(User.email.in_(["admin@demo.test", "student@demo.test"]))).rowcount,
        # Kept for past attempts' history, but never served again.
        "sample_questions_retired": db.execute(update(Question).where(Question.review_status == "sample")
                                               .values(review_status="retired")).rowcount,
    }
    counts["universities"] = db.execute(delete(University).where(University.name.like("%(DEMO)"))).rowcount
    # The synthetic source can no longer be chosen for imports.
    counts["demo_source_closed"] = db.execute(update(DataSource).where(DataSource.kind == "demo")
                                              .values(usage_status="prohibited")).rowcount
    db.commit()
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-demo", action="store_true", help="reference data only")
    ap.add_argument("--remove-demo", action="store_true", help="delete all demo data and demo accounts")
    ap.add_argument("--if-empty", action="store_true", help="do nothing if the database was already seeded")
    args = ap.parse_args()
    with SessionLocal() as db:
        if args.remove_demo:
            print(f"Removed demo data: {remove_demo(db)}")
            return
        if args.if_empty and db.scalar(select(Course.id).limit(1)) is not None:
            print("Already seeded; nothing to do.")
            return
        seed_reference(db)
        if not args.no_demo:
            seed_demo(db)
            seed_demo_accounts(db)
    print("Seed complete." + ("" if args.no_demo else " Demo data loaded (clearly marked DEMO)."))


if __name__ == "__main__":
    main()
