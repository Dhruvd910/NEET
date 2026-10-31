"""Normalisation of the many spellings used across counselling documents.

Unknown values are returned as None so the importer can raise a data-quality issue instead
of silently guessing.
"""
import re

CATEGORY_MAP = {
    "OPEN": "OPEN", "UR": "OPEN", "GEN": "OPEN", "GN": "OPEN", "GENERAL": "OPEN", "UNRESERVED": "OPEN",
    "OBC": "OBC", "OBC-NCL": "OBC", "OBC NCL": "OBC", "BC": "OBC",
    "SC": "SC", "ST": "ST",
    "EWS": "EWS", "GEN-EWS": "EWS",
}

QUOTA_MAP = {
    "AIQ": "AIQ", "ALL INDIA": "AIQ", "ALL INDIA QUOTA": "AIQ", "15% AIQ": "AIQ",
    "STATE": "STATE", "STATE QUOTA": "STATE", "SQ": "STATE", "85% STATE QUOTA": "STATE",
    "DEEMED": "DEEMED", "DEEMED/PAID SEATS QUOTA": "DEEMED", "DU": "DEEMED",
    "CENTRAL": "CENTRAL", "CENTRAL UNIVERSITY": "CENTRAL", "CU": "CENTRAL",
    "MANAGEMENT": "MANAGEMENT", "MQ": "MANAGEMENT",
    "NRI": "NRI", "NRI QUOTA": "NRI",
    "AIIMS": "AIIMS", "JIPMER": "JIPMER", "ESIC": "ESIC", "AFMS": "AFMS",
}

SEAT_TYPE_MAP = {"GENERAL": "GENERAL", "": "GENERAL", "PWD": "PWD", "PH": "PWD", "PWBD": "PWD"}

COURSE_MAP = {"MBBS": "MBBS", "BDS": "BDS", "BAMS": "BAMS", "BHMS": "BHMS", "BUMS": "BUMS", "BSMS": "BSMS",
              "BVSC": "BVSC", "BVSC&AH": "BVSC", "BVSC & AH": "BVSC", "BSC NURSING": "BSC_NURSING"}


def _key(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().upper())


def normalize_category(value: str | None) -> str | None:
    v = _key(value)
    if v.endswith(" PWD") or v.endswith("-PWD") or v.endswith("-PH"):
        v = re.split(r"[ -](PWD|PH)$", v)[0]
    return CATEGORY_MAP.get(v)


def normalize_quota(value: str | None) -> str | None:
    return QUOTA_MAP.get(_key(value))


def normalize_seat_type(value: str | None) -> str | None:
    return SEAT_TYPE_MAP.get(_key(value))


def normalize_course(value: str | None) -> str | None:
    return COURSE_MAP.get(_key(value).replace(".", ""))


def normalize_name(value: str) -> str:
    """Canonical key for college-name matching (aliases are stored with this key)."""
    v = value.lower()
    v = v.replace("&", " and ")
    v = re.sub(r"[^a-z0-9 ]", " ", v)
    v = re.sub(r"\b(the|of|and)\b", " ", v)
    v = re.sub(r"\bgovt\b", "government", v)
    v = re.sub(r"\bmed\b", "medical", v)
    v = re.sub(r"\bcoll\b", "college", v)
    return re.sub(r"\s+", " ", v).strip()
