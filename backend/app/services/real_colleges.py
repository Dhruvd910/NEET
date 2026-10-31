"""Real college catalogue from official and open sources.

1. Colleges and MBBS seats: the National Medical Commission's public "List of Colleges Teaching MBBS"
   (https://nmc.org.in, JSON behind that page). NMC's website terms allow copying for non-commercial use
   with the source kept, which every record does.
   NMC's per-college details add the official website, address, PIN code, email, phone and PG seats.
2. Map location: matched automatically from open data, and labelled as such (`location_source`): one bulk
   OpenStreetMap download matched by name and town, then Wikidata (CC0), then OpenStreetMap search through
   Nominatim (ODbL; at most one request a second, as its usage policy asks). Ambiguous matches are skipped.
3. Surroundings: OpenStreetMap through Overpass (services/places.py), once a college has a location.

Nothing is invented: fields a source does not give stay empty and the site says "Not available".
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    College, CollegeAlias, CollegeCourse, Course, DataSource, OutcomeRecord, University, VerificationStatus,
)
from app.services.normalize import normalize_name

DATA = Path(__file__).resolve().parents[2] / "data" / "sources"
NMC_PAGE = "https://nmc.org.in/page/information-desk-for-students-to-study-in-india-list-of-college-teaching-mbbs"
NMC_API = "https://nmc.org.in/college-courses/list?page=1&per_page=2000"
NMC_SOURCE = "National Medical Commission — List of Colleges Teaching MBBS"
NMC_TERMS = ("Reviewed the NMC website disclaimer (https://nmc.org.in/page/disclaimer): NMC authorizes copying of "
             "documents on the site for non-commercial purposes, keeping copyright notices. The platform is "
             "non-commercial and every record links to the NMC page. Get NMC's permission before any commercial use. "
             "Recorded by the catalogue importer; not legal advice.")
USER_AGENT = "NEETCompass/0.3 (non-commercial NEET-UG guidance site; medical college catalogue)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
SMALL_WORDS = {"AND", "OF", "THE", "FOR", "AT", "IN"}
ACRONYMS = {"ESIC", "AIIMS", "PGIMSR", "PGIMER", "KGMU", "GSVM", "GMERS", "IGMC", "SRMS", "NEIGRIHMS", "RIMS"}

# NMC spells some states differently from the rest of the platform.
STATE_FIX = {"andaman and nicobar islands": "Andaman and Nicobar Islands", "jammu and kashmir": "Jammu and Kashmir",
             "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
             "dadra and nagar haveli and daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
             "pondicherry": "Puducherry", "orissa": "Odisha", "delhi": "Delhi", "new delhi": "Delhi"}


def _http_json(url: str, *, data: bytes | None = None, headers: dict | None = None, timeout: int = 60):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                                          **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def academic_year(today: date | None = None) -> str:
    d = today or date.today()
    start = d.year if d.month >= 6 else d.year - 1  # Indian admissions run from mid-year
    return f"{start}-{str(start + 1)[-2:]}"


def state_name(raw: str) -> str:
    key = raw.strip().lower().replace("&", "and")
    key = re.sub(r"\s+", " ", key)
    return STATE_FIX.get(key) or " ".join(w if w in ("and",) else w.capitalize() for w in key.split())


def display_name(raw: str) -> str:
    """NMC writes some names in capitals; show those in title case (keeping short acronyms like ESIC, AIIMS)."""
    name = re.sub(r"\s+", " ", raw).strip().rstrip(".")
    if name.upper() != name:
        return name
    out = []
    for w in name.split(" "):
        core = re.sub(r"[^A-Z]", "", w)
        if core in SMALL_WORDS:
            out.append(w.lower())
        elif core in ACRONYMS or 1 < len(core) <= 3:
            out.append(w)
        else:
            out.append(w.capitalize())
    return " ".join(out)


def institution_type(row: dict) -> str:
    name, uni = row["college_name"], row.get("university_name") or ""
    if re.search(r"\bESIC\b|Armed Forces Medical", name, re.I):
        return "central"
    if re.search(r"deemed", uni, re.I):
        return "deemed"
    return "government" if row["management_type"] == "Government" else "private"


def recognition_label(text: str | None) -> str | None:
    """Short label from NMC's remark. Since 2024 every college gets an annual renewal, so the remark's opening
    words decide: recognized, a new college's Letter of Permission, or permitted but not yet recognized."""
    t = re.sub(r"\s+", " ", (text or "")).strip().lower()
    if not t:
        return None
    if re.match(r"(continuation of )?recogni[sz]ed", t) or re.search(r"recogni[sz]ed (for|from|with|u/s)", t[:200]):
        return "Recognized"
    if t.startswith("lop") or "letter of permission" in t[:120]:
        return "Letter of Permission (new college)"
    return "Permitted (not yet recognized)"


# ---------------------------------------------------------------- 1. official list

def fetch_nmc() -> dict:
    j = _http_json(NMC_API)
    snapshot = {"source": NMC_PAGE, "api": NMC_API, "fetched": datetime.now(timezone.utc).isoformat(), "rows": j["data"],
                "total_seats": j.get("total_seats")}
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "nmc_mbbs.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    return snapshot


def _source(db: Session, code: str, **defaults) -> DataSource:
    s = db.scalar(select(DataSource).where(DataSource.code == code))
    if s is None:
        s = DataSource(code=code, **defaults)
        db.add(s)
    return s


def import_nmc(db: Session, snapshot: dict) -> dict:
    fetched = datetime.fromisoformat(snapshot["fetched"])
    ay = academic_year(fetched.date())
    src = _source(db, "NMC", name="National Medical Commission", kind="official_portal", base_url="https://www.nmc.org.in")
    if src.usage_status == "unreviewed":
        src.usage_status, src.terms_url, src.terms_note = "allowed", "https://nmc.org.in/page/disclaimer", NMC_TERMS
        src.terms_reviewed_at, src.automated_access_permitted = fetched, True
    mbbs = db.scalar(select(Course).where(Course.code == "MBBS"))
    unis = {u.name: u for u in db.scalars(select(University))}
    existing = {c.code: c for c in db.scalars(select(College).where(College.is_demo.is_(False)))}
    taken_aliases = set(db.scalars(select(CollegeAlias.normalized)))
    counts = {"new": 0, "updated": 0, "seats": 0}

    for row in snapshot["rows"]:
        prov = dict(source_name=NMC_SOURCE, source_url=NMC_PAGE, collected_at=fetched, last_verified_at=fetched,
                    verification_status=VerificationStatus.verified,
                    publication_date=date.fromisoformat(row["updated_date"]) if row.get("updated_date") else None)
        uni = None
        if row.get("university_name"):
            uname = re.sub(r"\s+", " ", row["university_name"]).strip()
            uni = unis.get(uname)
            if uni is None:
                uni = unis[uname] = University(name=uname, state=state_name(row["state_name"]))
                db.add(uni)
                db.flush()
        code = row["college_code"].strip()
        c = existing.get(code)
        if c is None:
            c = College(code=code, is_demo=False)
            db.add(c)
            existing[code] = c
            counts["new"] += 1
        else:
            counts["updated"] += 1
        c.name = display_name(row["college_name"])
        c.state = state_name(row["state_name"])
        c.institution_type = institution_type(row)
        c.university_id = uni.id if uni else None
        c.established_year = row.get("year_of_inception_of_college") or row.get("inception_year")
        c.recognition_status = recognition_label(row.get("recognition_status"))
        c.recognition_note = (row.get("recognition_status") or "").replace("\r\n", "\n").strip() or None
        c.recognition_year = ay
        for k, v in prov.items():
            setattr(c, k, v)
        db.flush()
        for alias in {row["college_name"], c.name}:
            key = normalize_name(alias)
            if key and key not in taken_aliases:
                taken_aliases.add(key)
                db.add(CollegeAlias(college_id=c.id, alias=alias, normalized=key))
        cc = db.scalar(select(CollegeCourse).where(CollegeCourse.college_id == c.id, CollegeCourse.course_id == mbbs.id,
                                                   CollegeCourse.academic_year == ay))
        if cc is None:
            cc = CollegeCourse(college_id=c.id, course_id=mbbs.id, academic_year=ay)
            db.add(cc)
        cc.approved_intake = row.get("approved_seat")
        for k, v in prov.items():
            setattr(cc, k, v)
        counts["seats"] += row.get("approved_seat") or 0
    listed = {r["college_code"].strip() for r in snapshot["rows"]}
    gone = [c for code, c in existing.items() if code not in listed and c.source_name == NMC_SOURCE]
    for c in gone:  # dropped from NMC's list: keep the page, but say it is no longer current
        c.verification_status = VerificationStatus.outdated
    counts["no_longer_listed"] = len(gone)
    db.commit()
    return counts


def fetch_nmc_details(db: Session, snapshot: dict, limit: int | None = None, log=print) -> dict:
    """Per-college details NMC publishes (official website, address, PIN code, email, phone, PG seats).
    One request a second; responses are cached, so the job can be stopped and resumed."""
    cache, path = _cache("nmc_details.json")
    ids = {r["college_code"].strip(): r["college_id"] for r in snapshot["rows"]}
    colleges = db.scalars(select(College).where(College.code.in_(list(ids)))).all()[:limit]
    fetched = datetime.fromisoformat(snapshot["fetched"])
    ay = academic_year(fetched.date())
    counts = {"checked": 0, "websites": 0, "addresses": 0, "pg_seats": 0}
    for i, c in enumerate(colleges, 1):
        key = str(ids[c.code])
        if key not in cache:
            try:
                cache[key] = _http_json(f"https://nmc.org.in/college-courses/detail/{key}",
                                        headers={"X-Requested-With": "XMLHttpRequest"}, timeout=30).get("data") or {}
            except Exception:  # noqa: BLE001 — leave this college's details empty; a re-run retries it
                continue
            time.sleep(1)
        d = cache[key]
        counts["checked"] += 1
        site = (d.get("website") or "").strip()
        if site and site.lower() not in ("na", "n/a", "-", "nil"):
            c.website = site if site.startswith("http") else "http://" + site
            c.website_source = "NMC"
            counts["websites"] += 1
        if d.get("address"):
            c.address = re.sub(r"\s+", " ", d["address"]).strip()
            counts["addresses"] += 1
        c.pincode = (d.get("pincode") or "").strip() or c.pincode
        c.contact_email = (d.get("email") or "").strip() or None
        c.contact_phone = ", ".join(x.strip() for x in (d.get("mobile"), d.get("landline"))
                                    if x and x.strip().upper() not in ("NA", "N/A", "-", "NIL", "0")) or None
        if d.get("city") and not c.city:
            c.city = re.sub(r"[-(].*", "", d["city"]).strip() or None
        pg = [x for x in d.get("courses") or [] if x.get("course_type") in ("MD", "MS", "Diploma", "DNB")]
        db.execute(delete(OutcomeRecord).where(OutcomeRecord.college_id == c.id, OutcomeRecord.metric == "pg_seats"))
        if pg:
            seats = sum(x.get("approved_seat") or 0 for x in pg)
            db.add(OutcomeRecord(college_id=c.id, metric="pg_seats", value_numeric=seats, year=ay, comparable=True,
                                 value_text=f"{seats} postgraduate seats (MD/MS/Diploma) approved by NMC across {len(pg)} courses",
                                 source_name="National Medical Commission — college details", source_url=NMC_PAGE,
                                 collected_at=fetched, last_verified_at=fetched, verification_status=VerificationStatus.verified))
            counts["pg_seats"] += 1
        db.commit()  # save each college at once: never hold the write lock while waiting on the network
        if i % 25 == 0:
            path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            log(f"  NMC details {i}/{len(colleges)}: {counts}")
    db.commit()
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return counts


# ---------------------------------------------------------------- 2. location and website

OSM_FILE = "osm_medical_institutions_india.json"
OSM_QUERY = """[out:json][timeout:300];
area["ISO3166-1"="IN"][admin_level=2]->.in;
( nwr(area.in)["amenity"~"^(college|university|hospital|school)$"]["name"~"medical|AIIMS|ESIC|institute of .*sciences|health sciences|MBBS",i];
  nwr(area.in)["building"~"^(college|university|hospital)$"]["name"~"medical college|institute of medical",i]; );
out center tags;"""
# Words every medical college shares; matching uses the rest (its own name and its town).
GENERIC = set("""government govt medical college colleges hospital hospitals institute institution sciences science research
    centre center and of the for in at health university dental mbbs general district state super speciality specialty
    multi society trust foundation education educational campus new main city mission memorial teaching post graduate
    pg academy higher studies deemed be to dist district""".split())


def _tokens(*texts: str | None) -> set[str]:
    out = set()
    for t in texts:
        out |= set(normalize_name(t or "").split())
    return out


def fetch_osm_institutions() -> list[dict]:
    """Every medical college/hospital in India from OpenStreetMap, in a single Overpass request (kept on disk)."""
    r = httpx.post("https://overpass-api.de/api/interpreter", data={"data": OSM_QUERY},
                   headers={"User-Agent": USER_AGENT}, timeout=400)
    r.raise_for_status()
    els = r.json()["elements"]
    (DATA / OSM_FILE).write_text(json.dumps(els, ensure_ascii=False), encoding="utf-8")
    return els


def match_osm(db: Session, refresh: bool = False) -> dict:
    path = DATA / OSM_FILE
    els = fetch_osm_institutions() if refresh or not path.exists() else json.loads(path.read_text(encoding="utf-8"))
    places = []
    for e in els:
        t = e.get("tags", {})
        lat, lon = (e.get("lat"), e.get("lon")) if "lat" in e else ((e.get("center") or {}).get("lat"), (e.get("center") or {}).get("lon"))
        if lat is None or not t.get("name"):
            continue
        words = _tokens(t.get("name"), t.get("name:en"), t.get("official_name"), t.get("alt_name"), t.get("short_name"),
                        t.get("addr:city"), t.get("addr:district"), t.get("addr:suburb"), t.get("addr:place"), t.get("is_in"))
        places.append({"lat": lat, "lon": lon, "words": words, "tags": t,
                       "is_college": (t.get("amenity") or t.get("building")) in ("college", "university")})
    counts = {"located": 0, "websites": 0, "ambiguous": 0}
    for c in db.scalars(select(College).where(College.is_demo.is_(False), College.latitude.is_(None))):
        own = own_words([a.alias for a in c.aliases] or [c.name])
        if not own:
            continue
        scored = []
        for p in places:
            st = p["tags"].get("addr:state")
            if st and state_name(st) != c.state:
                continue
            share = len(own & p["words"]) / len(own)
            if share >= 0.75:
                scored.append((share, p["is_college"], p))
        if not scored:
            continue
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        best = scored[0]
        rivals = [s for s in scored[1:] if (s[0], s[1]) == (best[0], best[1])
                  and haversine_km(best[2]["lat"], best[2]["lon"], s[2]["lat"], s[2]["lon"]) > 3]
        if rivals:
            counts["ambiguous"] += 1  # two different places fit equally well: leave it rather than guess
            continue
        p = best[2]
        c.latitude, c.longitude = p["lat"], p["lon"]
        c.location_source = "OpenStreetMap (matched by name; check on the map)"
        t = p["tags"]
        c.city = c.city or t.get("addr:city") or t.get("addr:district")
        counts["located"] += 1
        site = t.get("website") or t.get("contact:website") or t.get("url")
        if site and not c.website:
            c.website = site if site.startswith("http") else "https://" + site
            c.website_source = "OpenStreetMap"
            counts["websites"] += 1
    db.commit()
    return counts


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from app.services.places import haversine_km as h
    return h(lat1, lon1, lat2, lon2)


def _cache(name: str) -> tuple[dict, Path]:
    path = DATA / name
    return (json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}), path


def _clean_query(name: str) -> str:
    q = re.sub(r"\(.*?\)", " ", name)
    q = re.sub(r"\b(and|&) (research|hospital|research centre|research center)\b.*", "", q, flags=re.I)
    return re.sub(r"\s+", " ", q).strip(" ,.")


def _place_ok(hit: dict, state: str, own: set[str]) -> bool:
    """A search hit counts only if it is the right kind of place, in the right state, and carries the college's own
    name words (for "Government Medical College, X" that is the town X)."""
    addr_state = (hit.get("address") or {}).get("state", "")
    same_state = state_name(addr_state) == state if addr_state else False
    kind_ok = (hit.get("category") or hit.get("class")) in ("amenity", "building", "landuse") and hit.get("type") in (
        "college", "university", "hospital", "school", "yes", "education", "institutional", "clinic")
    words = _tokens(hit.get("display_name"), hit.get("name"))
    return same_state and kind_ok and bool(own) and len(own & words) / len(own) >= 0.75


def own_words(names: list[str]) -> set[str]:
    return {w for w in _tokens(*names) - GENERIC if len(w) > 2}


def nominatim_lookup(name: str, state: str, own: set[str], cache: dict, pincode: str | None = None) -> dict | None:
    """OpenStreetMap search for one college (two phrasings at most); cached so re-runs never repeat a request."""
    full = _clean_query(name)
    queries = [f"{full}, {pincode}, India"] if pincode else []
    queries.append(f"{full}, {state}, India")
    if "," in full:
        queries.append(f"{full.split(',')[0]}, {full.split(',')[-1].strip()}, {state}, India")
    for query in dict.fromkeys(queries):
        if query not in cache:
            params = {"q": query, "format": "jsonv2", "addressdetails": 1, "extratags": 1, "limit": 5, "countrycodes": "in"}
            try:
                cache[query] = _http_json(f"{NOMINATIM}?{urllib.parse.urlencode(params)}", timeout=30)
            except Exception:  # noqa: BLE001 — a failed lookup just leaves the college without a location
                cache[query] = []
            time.sleep(1.1)  # Nominatim usage policy: at most one request per second
        for hit in cache[query]:
            if _place_ok(hit, state, own):
                return hit
    return None


def _website_from_osm(hit: dict) -> str | None:
    tags = hit.get("extratags") or {}
    url = tags.get("website") or tags.get("contact:website") or tags.get("url")
    if url and not url.startswith("http"):
        url = "https://" + url
    return url


def check_website(url: str) -> bool:
    """A website counts only if it answers. Many college sites block unknown clients, so 403 still counts."""
    try:
        r = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=15, follow_redirects=True)
        if re.search(r"defaultwebpage\.cgi|suspendedpage\.cgi|/cgi-sys/", str(r.url)):
            return False  # a hosting company's placeholder, not the college's site
        return r.status_code < 400 or r.status_code == 403
    except httpx.HTTPError:
        return False


def enrich_locations(db: Session, limit: int | None = None, log=print) -> dict:
    cache, path = _cache("nominatim_cache.json")
    todo = db.scalars(select(College).where(College.is_demo.is_(False), College.latitude.is_(None))).all()[:limit]
    found = 0
    for i, c in enumerate(todo, 1):
        hit = nominatim_lookup(c.name, c.state, own_words([a.alias for a in c.aliases] or [c.name]), cache, c.pincode)
        if hit:
            c.latitude, c.longitude = float(hit["lat"]), float(hit["lon"])
            c.location_source = "OpenStreetMap (matched by name; check on the map)"
            addr = hit.get("address") or {}
            c.city = c.city or addr.get("city") or addr.get("town") or addr.get("village") or addr.get("state_district")
            if not c.website and (site := _website_from_osm(hit)):
                c.website, c.website_source = site, "OpenStreetMap"
            found += 1
        db.commit()  # save each college at once: never hold the write lock while waiting on the network
        if i % 20 == 0:
            path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            log(f"  located {found}/{i}")
    db.commit()
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return {"checked": len(todo), "located": found}


WIKIDATA_API = "https://www.wikidata.org/w/api.php"


def _wikidata(params: dict, cache: dict) -> dict:
    """Wikidata's public API (CC0 data). Slow and polite: about one request every two seconds, backing off on 429."""
    key = json.dumps(params, sort_keys=True)
    if key in cache:
        return cache[key]
    url = f"{WIKIDATA_API}?{urllib.parse.urlencode({**params, 'format': 'json'})}"
    for wait in (5, 30, 120, 300):
        try:
            cache[key] = _http_json(url, timeout=30)
            time.sleep(2)
            return cache[key]
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(int(e.headers.get("Retry-After") or wait))
    raise RuntimeError("Wikidata keeps refusing requests; try again later (results so far are cached).")


def _claim(entity: dict, prop: str):
    return (entity.get("claims", {}).get(prop) or [{}])[0].get("mainsnak", {}).get("datavalue", {}).get("value")


def enrich_from_wikidata(db: Session, limit: int | None = None, log=print) -> dict:
    """Official website (P856) and coordinates (P625) from Wikidata, for colleges whose name and town match one item."""
    cache, path = _cache("wikidata_cache.json")
    todo = db.scalars(select(College).where(College.is_demo.is_(False),
                                            (College.website.is_(None)) | (College.latitude.is_(None)))).all()[:limit]
    counts = {"checked": 0, "websites": 0, "locations": 0}
    try:
        for i, c in enumerate(todo, 1):
            own = own_words([a.alias for a in c.aliases] or [c.name])
            text = re.sub(r"[^\w\s]", " ", _clean_query(c.name))
            hits = _wikidata({"action": "query", "list": "search", "srsearch": f"{text} haswbstatement:P17=Q668",
                              "srnamespace": 0, "srlimit": 5}, cache).get("query", {}).get("search", [])
            ids = [h["title"] for h in hits]
            ents = _wikidata({"action": "wbgetentities", "ids": "|".join(ids), "props": "labels|descriptions|claims",
                              "languages": "en"}, cache).get("entities", {}) if ids else {}
            fits = []
            for e in ents.values():
                label = e.get("labels", {}).get("en", {}).get("value", "")
                desc = e.get("descriptions", {}).get("en", {}).get("value", "")
                if (own and len(own & _tokens(label)) / len(own) >= 0.75
                        and re.search(r"medical|college|universit|institut|school|hospital", label + " " + desc, re.I)
                        and not re.search(r"post office|article|alumni|journal|railway|station", label + " " + desc, re.I)):
                    fits.append(e)
            if len(fits) == 1:
                e = fits[0]
                site, coord = _claim(e, "P856"), _claim(e, "P625")
                if site and not c.website:
                    c.website, c.website_source = site, "Wikidata"
                    counts["websites"] += 1
                if coord and c.latitude is None:
                    c.latitude, c.longitude, c.location_source = coord["latitude"], coord["longitude"], "Wikidata"
                    counts["locations"] += 1
            counts["checked"] += 1
            db.commit()  # save each college at once: never hold the write lock while waiting on the network
            if i % 25 == 0:
                path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                log(f"  Wikidata {i}/{len(todo)}: {counts}")
    finally:
        db.commit()
        path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return counts


def verify_websites(db: Session) -> dict:
    """Keeps only websites that answer; the rest are cleared rather than shown as broken links."""
    rows = db.scalars(select(College).where(College.is_demo.is_(False), College.website.is_not(None))).all()
    with ThreadPoolExecutor(8) as pool:
        ok = list(pool.map(check_website, [c.website for c in rows]))
    dropped = 0
    for c, good in zip(rows, ok):
        if not good:
            c.website, c.website_source = None, None
            dropped += 1
    db.commit()
    return {"checked": len(rows), "removed_unreachable": dropped}
