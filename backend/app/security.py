"""Password hashing (stdlib scrypt), JWT session cookies, CSRF, auth dependencies, rate limiting."""
import base64
import hashlib
import hmac
import logging
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Role, User

COOKIE_NAME = "neet_session"
CSRF_COOKIE = "neet_csrf"
CSRF_HEADER = "x-csrf-token"
log = logging.getLogger(__name__)
_SCRYPT = dict(n=2**14, r=8, p=1, dklen=64)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def create_token(user: User) -> str:
    s = get_settings()
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=s.jwt_expiry_minutes),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def _user_from_request(request: Request, db: Session) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    auth = request.headers.get("authorization", "")
    if not token and auth.lower().startswith("bearer "):
        token = auth[7:]
    if not token:
        return None
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return db.get(User, int(payload["sub"]))


def csrf_token_for(session_token: str) -> str:
    """Signed double-submit token: bound to the session, so a forged cookie is useless."""
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, b"csrf:" + session_token.encode(), hashlib.sha256).hexdigest()


def csrf_ok(request: Request) -> bool:
    """Unsafe requests authenticated by the session cookie must echo the CSRF token in a header.

    Requests without a session cookie (anonymous, or bearer-token API clients) are not exposed to
    CSRF, because browsers never attach bearer tokens automatically.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    session = request.cookies.get(COOKIE_NAME)
    if not session:
        return True
    sent = request.headers.get(CSRF_HEADER, "")
    return bool(sent) and hmac.compare_digest(sent, csrf_token_for(session))


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user = _user_from_request(request, db)
    return user if user is not None and has_consent(user) else None


def has_consent(user: User) -> bool:
    return not user.is_minor or user.guardian_consent_status == "verified"


def authenticated_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Signed-in user, even a minor still waiting for guardian consent (account endpoints only)."""
    user = _user_from_request(request, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in.")
    return user


def current_user(user: User = Depends(authenticated_user)) -> User:
    """Signed-in user allowed to use personal-data features."""
    if not has_consent(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Waiting for your parent or guardian to confirm consent. "
                            "They were sent an email with a link.")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required.")
    return user


class RateLimiter:
    """In-memory sliding-window limiter, per process. Used when REDIS_URL is not set."""

    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


class RedisRateLimiter:
    """Fixed-window counter shared by every worker/instance through Redis.

    If Redis is unreachable the request is allowed (fail open) and the error is logged, so an
    outage of the limiter never takes the site down; the in-memory limiter still applies.
    """

    def __init__(self, client, fallback: RateLimiter | None = None):
        self.client = client
        self.fallback = fallback or RateLimiter()

    def check(self, key: str, limit: int, window: float = 60.0) -> bool:
        bucket = int(time.time() // window)
        k = f"rl:{key}:{bucket}"
        try:
            pipe = self.client.pipeline()
            pipe.incr(k)
            pipe.expire(k, int(window) + 1)
            count, _ = pipe.execute()
        except Exception as exc:  # noqa: BLE001 - any Redis error
            log.warning("rate limiter: Redis unavailable (%s); using in-process limiter", exc)
            return self.fallback.check(key, limit, window)
        return int(count) <= limit


def make_rate_limiter():
    url = get_settings().redis_url
    if not url:
        return RateLimiter()
    import redis
    return RedisRateLimiter(redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5))


rate_limiter = make_rate_limiter()
