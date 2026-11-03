"""Admin pages: one page with tabs. Every form posts to /admin/<tab>/<action>, which calls the admin API
function (so permissions, validation and the audit log stay in one place) and re-renders the tab."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy import func, or_, select

from app.models import LoginEvent, Role, User
from app.routers import admin as admin_api
from app.services import admin_activity
from app.web.core import Page, admin_page, templates
from app.web.routes_student import error_text

router = APIRouter(include_in_schema=False)
templates.env.globals.update(triage=admin_activity.triage, spark=admin_activity.spark)

TABS = [("overview", "Overview"), ("users", "Students"), ("imports", "Imports"), ("sources", "Sources"), ("rules", "Eligibility rules"),
        ("info", "Info pages"), ("colleges", "Colleges"), ("issues", "Issues & reviews")]
TABLE_COLUMNS = {
    "cutoffs": "college_code or college_name, course, authority, exam_year, round, quota, category, closing_rank "
               "(+ opening_rank, seat_type, rank_basis, domicile_required, round_name)",
    "seat_matrix": "college_code or college_name, course, authority, exam_year, round, quota, category, seats (+ seat_type)",
    "fees": "college_code or college_name, academic_year (2025-26), fee_type, amount_inr, period "
            "(+ course, quota, mandatory, refundable, note)",
}


def _v(form, k: str):
    v = (form.get(k) or "").strip() if isinstance(form.get(k), str) else form.get(k)
    return v or None


def _int(form, k: str):
    v = _v(form, k)
    return int(v) if v is not None and str(v).lstrip("-").isdigit() else None


def _float(form, k: str):
    try:
        return float(_v(form, k)) if _v(form, k) is not None else None
    except ValueError:
        return None


def _render(p: Page, tab: str, msg: str | None = None, error: str | None = None, status_code: int = 200, **extra):
    tab = tab if tab in dict(TABS) else "overview"
    u, db = p.user, p.db
    ctx = {"stats": admin_api.stats(u, db)}
    if tab == "overview":
        ctx.update(readiness=admin_api.readiness(u, db), vitals=admin_activity.vitals(db),
                   feed=admin_activity.activity_feed(db, limit=12))
    elif tab == "imports":
        sources = admin_api.data_sources(u, db)
        ctx.update(allowed=[s for s in sources if s["usage_status"] == "allowed"], jobs=admin_api.jobs(u, db),
                   docs=admin_api.documents(u, db), TABLE_COLUMNS=TABLE_COLUMNS,
                   no_real_source=not any(s["usage_status"] == "allowed" and s["kind"] != "demo" for s in sources))
    elif tab == "sources":
        ctx["sources"] = admin_api.data_sources(u, db)
    elif tab == "rules":
        ctx["r"] = admin_api.eligibility_rules(u, db)
    elif tab == "info":
        ctx["articles"] = admin_api.info_articles(u, db)
    elif tab == "issues":
        ctx.update(issues=admin_api.issues("open", u, db), reviews=admin_api.pending_reviews(u, db))
    elif tab == "users":
        ctx.update(users_view(db, extra.pop("q", None) or ""))
    return p.render("admin.html", status_code=status_code, TABS=TABS, tab=tab, msg=msg, error=error, **ctx, **extra)


def users_view(db, q: str) -> dict:
    """Who has signed up and who signs in: totals, the user list (newest first) and the latest sign-ins."""
    now = datetime.now(timezone.utc)
    day, week = now - timedelta(days=1), now - timedelta(days=7)
    count = lambda *w: db.scalar(select(func.count()).select_from(User).where(*w)) or 0  # noqa: E731
    active = lambda since: db.scalar(select(func.count(func.distinct(LoginEvent.user_id)))  # noqa: E731
                                     .where(LoginEvent.at >= since)) or 0
    totals = {"users": count(), "google": count(User.google_sub.is_not(None)), "phone": count(User.tekurious_user_id.is_not(None)), "admins": count(User.role == Role.admin),
              "new_7d": count(User.created_at >= week), "active_24h": active(day), "active_7d": active(week),
              "signins_24h": db.scalar(select(func.count()).select_from(LoginEvent).where(LoginEvent.at >= day)) or 0}
    stmt = select(User).order_by(User.created_at.desc()).limit(300)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(like), func.lower(User.name).like(like), User.phone.like(like)))
    events = db.execute(select(LoginEvent, User.email, User.name, User.phone).join(User, User.id == LoginEvent.user_id)
                        .order_by(LoginEvent.at.desc()).limit(100)).all()
    return {"totals": totals, "users": db.scalars(stmt).all(), "events": events, "q": q}


@router.get("/admin/students/{user_id}", response_class=HTMLResponse)
def student_file(user_id: int, p: Page = Depends(admin_page)):
    """One student's activity ("case file"). Every view is written to the audit log."""
    target = p.db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "Student not found")
    admin_api.audit(p.db, p.user, "view_student", "user", user_id, {})
    p.db.commit()
    return p.render("admin_student.html", TABS=TABS, tab="users", msg=None, error=None,
                    stats=admin_api.stats(p.user, p.db), f=admin_activity.student_file(p.db, target))


@router.get("/admin", response_class=HTMLResponse)
def admin(p: Page = Depends(admin_page), tab: str = "overview", open: int | None = None, prefill: str | None = None,  # noqa: A002
          q: str | None = None):
    pre = None
    if prefill:  # "authority_id|year|quota" from a missing-rule button
        a, y, q = (prefill.split("|") + ["", "", ""])[:3]
        pre = {"authority_id": int(a) if a.isdigit() else None, "exam_year": y, "quota": q}
    return _render(p, tab, open_id=open, prefill=pre, q=q)


async def _import_table(p: Page, f):
    j = await admin_api.upload_table(f.get("kind"), file=f["file"], data_source_code=f.get("data_source_code") or "",
                                     source_name=_v(f, "source_name") or "", source_url=_v(f, "source_url"),
                                     publication_date=date.fromisoformat(f["publication_date"]) if _v(f, "publication_date") else None,
                                     admin=p.user, db=p.db)
    return f"Import {j['status']}: {j['inserted']} new, {j['updated']} updated, {j['skipped']} skipped."


async def _upload_document(p: Page, f):
    d = await admin_api.upload_document(file=f["file"], title=_v(f, "title") or "", url=_v(f, "url"),
                                        authority=_v(f, "authority"), doc_type=_v(f, "doc_type") or "notice",
                                        exam_year=_int(f, "exam_year"), state=None,
                                        publication_date=date.fromisoformat(f["publication_date"]) if _v(f, "publication_date") else None,
                                        admin=p.user, db=p.db)
    return f"Indexed “{d['title']}” ({d['chunks']} passages)."


async def _dispatch(p: Page, action: str, f) -> str:
    u, db = p.user, p.db
    if action == "import":
        return await _import_table(p, f)
    if action == "document":
        return await _upload_document(p, f)
    if action == "backfill":
        return f"Embedded {admin_api.embeddings_backfill(u, db)['embedded']} passage(s)."
    if action == "ocr":
        return f"OCR {admin_api.ocr_document(_int(f, 'id'), u, db)['status']}."
    if action == "terms":
        admin_api.review_terms(_int(f, "id"), admin_api.TermsReviewIn(
            usage_status=f.get("usage_status"), terms_url=_v(f, "terms_url"), terms_note=_v(f, "terms_note") or "",
            attribution_text=_v(f, "attribution_text"), automated_access_permitted=bool(f.get("automated"))), u, db)
        return "Saved terms review."
    if action == "source":
        admin_api.create_source(admin_api.SourceIn(code=_v(f, "code") or "", name=_v(f, "name") or "",
                                                   kind=f.get("kind"), base_url=_v(f, "base_url")), u, db)
        return "Source added. Review its terms before importing."
    if action == "rule":
        key, raw = f.get("rule_key"), f.get("value")
        admin_api.upsert_rule(admin_api.RuleIn(
            authority_id=_int(f, "authority_id") or 0, exam_year=_int(f, "exam_year") or 0, quota=_v(f, "quota") or "",
            rule_key=key, value=(raw == "true") if key == "open_category_accessible" else raw,
            description=_v(f, "description"), source_name=_v(f, "source_name") or "", source_url=_v(f, "source_url") or "",
            publication_date=_v(f, "publication_date")), u, db)
        return "Rule saved as unverified. Verify it below after checking the source."
    if action == "verify":
        admin_api.verify(admin_api.VerifyIn(entity_type=f.get("entity_type"), entity_id=_int(f, "id") or 0,
                                            status="verified"), u, db)
        return "Marked verified."
    if action == "article":
        admin_api.edit_article(_int(f, "id"), admin_api.ArticlePatch(
            title=_v(f, "title"), body=_v(f, "body"), exam_year=_int(f, "exam_year"), source_name=_v(f, "source_name"),
            source_url=_v(f, "source_url"), source_document_id=_int(f, "source_document_id")), u, db)
        return "Saved. Now verify it."
    if action == "college":
        c = admin_api.create_college(admin_api.CollegeIn(
            code=_v(f, "code") or "", name=_v(f, "name") or "", state=_v(f, "state") or "", city=_v(f, "city"),
            institution_type=f.get("institution_type"), website=_v(f, "website"), latitude=_float(f, "latitude"),
            longitude=_float(f, "longitude"), aliases=[a.strip() for a in (f.get("aliases") or "").split(";") if a.strip()],
            source_name=_v(f, "source_name") or "", source_url=_v(f, "source_url")), u, db)
        return f"College #{c['id']} created (unverified)."
    if action == "nearby":
        return f"Saved {admin_api.refresh_nearby(_int(f, 'id') or 0, u, db)['places']} nearby place(s)."
    if action == "issue":
        admin_api.patch_issue(_int(f, "id"), admin_api.IssuePatch(status=f.get("status")), u, db)
        return "Issue updated."
    if action == "role":
        target = p.db.get(User, _int(f, "id") or 0)
        if target is None:
            raise HTTPException(404, "User not found")
        if target.id == u.id:
            raise HTTPException(422, "You can't change your own role.")
        target.role = Role.admin if f.get("role") == "admin" else Role.student
        admin_api.audit(db, u, "set_role", "user", target.id, {"role": target.role.value})
        db.commit()
        return f"{target.label} is now {'an admin' if target.role == Role.admin else 'a student'}."
    if action == "review":
        approve = f.get("status") == "approved"
        admin_api.moderate(_int(f, "id"), admin_api.ModerateIn(status="approved" if approve else "rejected",
                                                               note=None if approve else "Violates guidelines"), u, db)
        return "Review approved." if approve else "Review rejected."
    raise HTTPException(404, "Unknown action")


@router.post("/admin/{tab}/{action}", response_class=HTMLResponse)
async def admin_action(tab: str, action: str, request: Request, p: Page = Depends(admin_page)):
    f = await request.form()
    try:
        msg = await _dispatch(p, action, f)
    except (HTTPException, ValidationError, ValueError) as e:
        p.db.rollback()
        return _render(p, tab, error=error_text(e), status_code=422)
    return _render(p, tab, msg=msg)
