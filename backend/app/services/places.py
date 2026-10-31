"""Nearby places (transport, pharmacies, hospitals, banks…) from a maps/places provider.

Provider: OpenStreetMap through the Overpass API (PLACES_PROVIDER=overpass).
- Licence: OpenStreetMap data is ODbL. Storing it is allowed; the UI must show
  "© OpenStreetMap contributors" (saved on every row as `attribution`).
- Usage policy: the public Overpass instance is for light use. Refreshes are admin-triggered,
  one college at a time. For bulk refreshes, run your own Overpass instance (OVERPASS_URL).
Commercial providers (Google Places, Mapbox, MapmyIndia) can be added as another `fetch_*`
function, but check their terms first: Google's Places terms restrict caching place data.

Only facts the provider gives are stored (name, type, coordinates). Distances are straight-line
and labelled as approximate; opening hours or "open now" are never claimed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import College, NearbyPlace

OSM_ATTRIBUTION = "© OpenStreetMap contributors (ODbL)"

# kind -> (Overpass selectors, search radius in metres, max results kept)
KINDS: dict[str, tuple[list[str], int, int]] = {
    "bus_stop": (['node["highway"="bus_stop"]'], 1500, 3),
    "railway": (['node["railway"="station"]["station"!="subway"]'], 15000, 2),
    "metro": (['node["station"="subway"]', 'node["railway"="station"]["subway"="yes"]'], 5000, 2),
    "airport": (['nwr["aeroway"="aerodrome"]["iata"]'], 80000, 1),
    "pharmacy": (['nwr["amenity"="pharmacy"]'], 2000, 3),
    "hospital": (['nwr["amenity"="hospital"]'], 5000, 3),
    "clinic": (['nwr["amenity"="clinic"]', 'nwr["amenity"="doctors"]'], 2000, 2),
    "police": (['nwr["amenity"="police"]'], 5000, 1),
    "bank_atm": (['nwr["amenity"="atm"]', 'nwr["amenity"="bank"]'], 2000, 3),
    "grocery": (['nwr["shop"="supermarket"]', 'nwr["shop"="convenience"]', 'nwr["shop"="greengrocer"]'], 2000, 3),
    "restaurant": (['nwr["amenity"="restaurant"]', 'nwr["amenity"="fast_food"]', 'nwr["amenity"="food_court"]'], 1500, 4),
    "cafe": (['nwr["amenity"="cafe"]'], 1500, 2),
    "stay": (['nwr["tourism"="hostel"]', 'nwr["tourism"="guest_house"]'], 3000, 3),
    "laundry": (['nwr["shop"="laundry"]', 'nwr["shop"="dry_cleaning"]'], 2000, 2),
    "stationery": (['nwr["shop"="stationery"]', 'nwr["shop"="books"]', 'nwr["shop"="copyshop"]'], 2000, 3),
    "library": (['nwr["amenity"="library"]'], 5000, 2),
    "gym": (['nwr["leisure"="fitness_centre"]'], 3000, 2),
    "park": (['nwr["leisure"="park"]'], 2000, 2),
    "mall": (['nwr["shop"="mall"]', 'nwr["amenity"="cinema"]'], 8000, 2),
}

# How the college page groups places. Older/demo rows use "atm" and "pg"; they map to the same groups.
CATEGORIES: dict[str, list[str]] = {
    "Getting around": ["bus_stop", "metro", "railway", "airport"],
    "Health & safety": ["hospital", "clinic", "pharmacy", "police"],
    "Food": ["restaurant", "cafe"],
    "Stay (outside campus)": ["stay", "pg"],
    "Daily needs": ["grocery", "bank_atm", "atm", "laundry", "stationery"],
    "Study & leisure": ["library", "gym", "park", "mall"],
}
KIND_CATEGORY = {k: cat for cat, kinds in CATEGORIES.items() for k in kinds}


def walk_minutes(distance_km: float | None) -> int | None:
    """Rough walking time: straight-line distance x 1.3 for real paths, at 4.5 km/h. Only under 3 km."""
    if distance_km is None or distance_km > 3:
        return None
    return max(1, round(distance_km * 1.3 / 4.5 * 60))


class PlacesError(RuntimeError):
    pass


@dataclass
class Place:
    kind: str
    name: str
    lat: float
    lon: float
    external_id: str


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def overpass_query(lat: float, lon: float) -> str:
    parts = []
    for kind, (selectors, radius, _) in KINDS.items():
        for sel in selectors:
            parts.append(f'{sel}(around:{radius},{lat},{lon});')
    return f"[out:json][timeout:60];({''.join(parts)});out center tags;"


def _classify(tags: dict) -> str | None:
    if tags.get("highway") == "bus_stop":
        return "bus_stop"
    if tags.get("station") == "subway" or (tags.get("railway") == "station" and tags.get("subway") == "yes"):
        return "metro"
    if tags.get("railway") == "station":
        return "railway"
    if tags.get("aeroway") == "aerodrome":
        return "airport"
    amenity, shop, leisure = tags.get("amenity"), tags.get("shop"), tags.get("leisure")
    if amenity in ("pharmacy", "hospital", "police", "library", "cafe"):
        return amenity
    if amenity in ("clinic", "doctors"):
        return "clinic"
    if amenity in ("atm", "bank"):
        return "bank_atm"
    if amenity in ("restaurant", "fast_food", "food_court"):
        return "restaurant"
    if amenity == "cinema" or shop == "mall":
        return "mall"
    if tags.get("tourism") in ("hostel", "guest_house"):
        return "stay"
    if shop in ("supermarket", "convenience", "greengrocer"):
        return "grocery"
    if shop in ("laundry", "dry_cleaning"):
        return "laundry"
    if shop in ("stationery", "books", "copyshop"):
        return "stationery"
    if leisure == "fitness_centre":
        return "gym"
    if leisure == "park":
        return "park"
    return None


def parse_overpass(data: dict) -> list[Place]:
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        name = tags.get("name:en") or tags.get("name")
        kind = _classify(tags)
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if not (name and kind and lat is not None and lon is not None):
            continue  # unnamed features are not useful to students
        out.append(Place(kind=kind, name=name[:200], lat=float(lat), lon=float(lon),
                         external_id=f"osm:{el.get('type')}/{el.get('id')}"))
    return out


def fetch_overpass(lat: float, lon: float) -> list[Place]:
    s = get_settings()
    try:
        r = httpx.post(s.overpass_url, data={"data": overpass_query(lat, lon)},
                       headers={"User-Agent": s.places_user_agent}, timeout=90)
        r.raise_for_status()
        return parse_overpass(r.json())
    except (httpx.HTTPError, ValueError) as exc:
        raise PlacesError(f"Overpass request failed: {exc}") from exc


def refresh_nearby(db: Session, college: College, fetch=None) -> list[NearbyPlace]:
    """Replace a college's provider-sourced nearby places with fresh results."""
    s = get_settings()
    if s.places_provider != "overpass" and fetch is None:
        raise PlacesError("No places provider configured. Set PLACES_PROVIDER=overpass.")
    if college.is_demo:
        raise PlacesError("Demo colleges have fictional locations; nearby places are not fetched for them.")
    if college.latitude is None or college.longitude is None:
        raise PlacesError("Add the college's verified latitude/longitude first.")
    places = (fetch or fetch_overpass)(college.latitude, college.longitude)

    best: dict[str, list[tuple[float, Place]]] = {}
    for p in places:
        best.setdefault(p.kind, []).append((haversine_km(college.latitude, college.longitude, p.lat, p.lon), p))
    now = datetime.now(timezone.utc)
    db.execute(delete(NearbyPlace).where(NearbyPlace.college_id == college.id, NearbyPlace.is_demo.is_(False)))
    rows = []
    for kind, items in best.items():
        keep = KINDS[kind][2]
        seen = set()
        for dist, p in sorted(items, key=lambda x: x[0]):
            if p.name in seen:
                continue
            seen.add(p.name)
            rows.append(NearbyPlace(
                college_id=college.id, kind=kind, name=p.name, distance_km=round(dist, 1), latitude=p.lat,
                longitude=p.lon, provider="openstreetmap", attribution=OSM_ATTRIBUTION, external_id=p.external_id,
                route_url=(f"https://www.openstreetmap.org/directions?route={college.latitude}%2C{college.longitude}"
                           f"%3B{p.lat}%2C{p.lon}"),
                last_checked_at=now, is_demo=False))
            if len(seen) >= keep:
                break
    db.add_all(rows)
    db.commit()
    return rows
