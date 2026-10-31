import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal
from app.routers import admin, assistant, auth, colleges, counselling, mock_tests, practice, profile
from app.security import COOKIE_NAME, CSRF_COOKIE, csrf_ok, csrf_token_for, rate_limiter

settings = get_settings()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"ts": self.formatTime(record), "level": record.levelname, "logger": record.name,
                "msg": record.getMessage()}
        data.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter() if settings.log_json
                      else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)
access_log = logging.getLogger("app.access")

app = FastAPI(
    title="NEET Guidance Platform API",
    version="0.2.0",
    description="Source-backed NEET-UG guidance: catalog, historical cutoff matching, costs, mock tests, assistant.",
)


def client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def security_and_limits(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/auth/login") or path.startswith("/api/auth/register"):
        bucket, limit = "auth", settings.rate_limit_auth
    elif path.startswith("/api/auth/guardian-consent"):
        bucket, limit = "auth", settings.rate_limit_auth
    elif path.startswith("/api/assistant/messages"):
        bucket, limit = "assistant", settings.rate_limit_assistant
    else:
        bucket, limit = "default", settings.rate_limit_default
    if not rate_limiter.check(f"{bucket}:{client_ip(request)}", limit):
        return JSONResponse({"detail": "Too many requests — please wait a minute and try again."}, status_code=429)
    # Login/register start a new session, so a stale cookie must not block them.
    csrf_exempt = path in ("/api/auth/login", "/api/auth/register")
    if path.startswith("/api/") and not csrf_exempt and not csrf_ok(request):
        return JSONResponse({"detail": "Security check failed (missing or invalid CSRF token). Reload the page "
                                       "and try again."}, status_code=403)
    response = await call_next(request)
    # Sessions created before CSRF tokens existed (or with a cleared cookie) get one on the next request.
    session = request.cookies.get(COOKIE_NAME)
    if session and not request.cookies.get(CSRF_COOKIE) and "set-cookie" not in response.headers:
        response.set_cookie(CSRF_COOKIE, csrf_token_for(session), httponly=False, samesite="lax",
                            secure=settings.cookie_secure, path="/")
    return response


@app.middleware("http")
async def request_log(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        access_log.exception("unhandled error", extra={"extra_fields": {"request_id": rid, "path": request.url.path}})
        raise
    ms = round((time.perf_counter() - start) * 1000, 1)
    response.headers["x-request-id"] = rid
    # Never log query strings or bodies: they can contain personal data.
    access_log.info("%s %s %s %sms", request.method, request.url.path, response.status_code, ms,
                    extra={"extra_fields": {"request_id": rid, "method": request.method, "path": request.url.path,
                                            "status": response.status_code, "ms": ms}})
    return response


# Added last so it runs first: preflight requests are answered before rate limiting and CSRF.
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    # Consistent shape: {"detail": "<first human-readable message>", "errors": [...]}
    errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()]
    first = errors[0]["msg"].removeprefix("Value error, ") if errors else "Invalid request"
    return JSONResponse({"detail": first, "errors": errors}, status_code=422)


for r in (auth.router, profile.router, mock_tests.router, colleges.router, counselling.router,
          assistant.router, practice.router, admin.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    """Liveness: the process is up. Use /api/ready for load-balancer readiness."""
    return {"status": "ok", "llm_configured": settings.llm_configured, "llm_provider": settings.llm_provider}


@app.get("/api/ready")
def ready():
    """Readiness: the database answers. Returns 503 otherwise."""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).error("readiness check failed: %s", exc)
        return JSONResponse({"status": "unavailable", "database": "error"}, status_code=503)
    return {"status": "ok", "database": "ok"}
