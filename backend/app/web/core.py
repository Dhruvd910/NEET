"""Server-rendered website: Jinja2 templates + HTMX, served by the same FastAPI app as the JSON API.

Pages call the service layer directly (no HTTP round trip to /api). Interactivity uses HTMX attributes
in the templates; the CSRF token is sent by HTMX on every request (see base.html), and the existing
middleware checks it for all unsafe requests.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Role, User
from app.security import COOKIE_NAME, _user_from_request, csrf_token_for, has_consent

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=WEB_DIR / "templates")

STATUS_STYLE = {
    "verified": "bg-emerald-50 text-emerald-800 ring-emerald-200",
    "demo": "bg-amber-50 text-amber-900 ring-amber-300",
    "unverified": "bg-slate-100 text-slate-700 ring-slate-300",
    "pending_review": "bg-sky-50 text-sky-800 ring-sky-200",
    "outdated": "bg-orange-50 text-orange-800 ring-orange-200",
    "conflicting": "bg-red-50 text-red-800 ring-red-200",
}
STATUS_LABEL = {
    "verified": "Verified", "demo": "DEMO data — not real", "unverified": "Unverified",
    "pending_review": "Pending verification", "outdated": "Outdated", "conflicting": "Conflicting sources",
}
FIT_STYLE = {
    "Stronger historical fit": "bg-teal-50 text-teal-800 ring-teal-200",
    "Possible / uncertain": "bg-indigo-50 text-indigo-800 ring-indigo-200",
    "Ambitious": "bg-rose-50 text-rose-800 ring-rose-200",
}
SUBJECT_STYLE = {
    "Physics": ("Atom", "from-sky-500 to-blue-600", "bg-sky-50 text-sky-800 ring-sky-200"),
    "Chemistry": ("Flask", "from-amber-500 to-orange-600", "bg-amber-50 text-amber-900 ring-amber-200"),
    "Botany": ("Leaf", "from-emerald-500 to-teal-600", "bg-emerald-50 text-emerald-800 ring-emerald-200"),
    "Zoology": ("Dna", "from-violet-500 to-purple-600", "bg-violet-50 text-violet-800 ring-violet-200"),
    "Biology": ("Dna", "from-emerald-500 to-violet-600", "bg-emerald-50 text-emerald-800 ring-emerald-200"),
}
NAV_LINKS = [("/dashboard", "Dashboard"), ("/predictor", "Predictor"), ("/colleges", "Colleges"), ("/compare", "Compare"),
             ("/practice", "Practice"), ("/study-plan", "Study plan"), ("/assistant", "Assistant")]
NAV_MORE = [("/mock-tests", "Mock log"), ("/counselling", "Counselling"), ("/neet", "NEET info"), ("/careers", "Careers")]
STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Delhi", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan",
    "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Lakshadweep",
]
CATEGORIES = ["OPEN", "EWS", "OBC", "SC", "ST"]
KIND_LABEL = {
    "bus_stop": "Bus stop", "railway": "Railway station", "metro": "Metro station", "airport": "Airport",
    "hospital": "Hospital", "clinic": "Clinic / doctor", "pharmacy": "Pharmacy", "police": "Police station",
    "restaurant": "Restaurant / mess", "cafe": "Café", "stay": "Hostel / guest house", "pg": "PG / private hostel",
    "grocery": "Grocery / market", "bank_atm": "Bank / ATM", "atm": "Bank / ATM", "laundry": "Laundry",
    "stationery": "Stationery / books / xerox", "library": "Library", "gym": "Gym", "park": "Park", "mall": "Mall / cinema",
}
CATEGORY_HINT = {
    "Stay (outside campus)": "Listings come from map data, not inspections. Visit before paying, check safety, and ask current students.",
    "Health & safety": "In an emergency call 112.",
}


def inr(v) -> str:
    if v is None:
        return "Not available"
    v = int(round(v))
    s, neg = str(abs(v)), v < 0
    if len(s) > 3:  # Indian digit grouping: 12,34,567
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if neg else "") + "₹" + s


def num(v) -> str:
    return "—" if v is None else inr(v).replace("₹", "")


def fmt_date(v) -> str:
    if not v:
        return "—"
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return v
    if isinstance(v, (datetime, date)):
        return f"{v.day} {v.strftime('%b %Y')}"
    return str(v)


def clock(seconds: int) -> str:
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


templates.env.filters.update(inr=inr, num=num, date=fmt_date, clock=clock, urlquote=quote)
templates.env.globals.update(STATUS_STYLE=STATUS_STYLE, STATUS_LABEL=STATUS_LABEL, FIT_STYLE=FIT_STYLE,
                             SUBJECT_STYLE=SUBJECT_STYLE, NAV_LINKS=NAV_LINKS, NAV_MORE=NAV_MORE,
                             STATES=STATES, CATEGORIES=CATEGORIES, SECTIONS=["Physics", "Chemistry", "Botany", "Zoology"],
                             KIND_LABEL=KIND_LABEL, CATEGORY_HINT=CATEGORY_HINT, settings=get_settings())


class LoginRequired(Exception):
    """Raised by page dependencies; the app turns it into a redirect to /login?next=…"""

    def __init__(self, next_url: str):
        self.next_url = next_url


class GuardianPending(Exception):
    """A minor whose guardian has not confirmed consent tried to open a personal-data page."""


class AdminRequired(Exception):
    pass


@dataclass
class Page:
    request: Request
    db: Session
    user: User | None

    @property
    def csrf(self) -> str:
        session = self.request.cookies.get(COOKIE_NAME)
        return csrf_token_for(session) if session else ""

    @property
    def is_htmx(self) -> bool:
        return self.request.headers.get("hx-request") == "true"

    def render(self, template: str, status_code: int = 200, **ctx):
        return templates.TemplateResponse(self.request, template, {"page": self, "me": self.user, **ctx},
                                          status_code=status_code)


def page(request: Request, db: Session = Depends(get_db)) -> Page:
    """Any visitor; `user` is set when signed in (even a minor still waiting for consent)."""
    return Page(request, db, _user_from_request(request, db))


def student_page(p: Page = Depends(page)) -> Page:
    """Signed-in visitor allowed to use personal-data features."""
    if p.user is None:
        target = p.request.url.path + (f"?{p.request.url.query}" if p.request.url.query else "")
        raise LoginRequired(target)
    if not has_consent(p.user):
        raise GuardianPending()
    return p


def admin_page(p: Page = Depends(student_page)) -> Page:
    if p.user.role != Role.admin:
        raise AdminRequired()
    return p
