import json
import logging
import time
import uuid
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal
from app.routers import admin, assistant, auth, colleges, counselling, mock_tests, practice, profile
from app.security import COOKIE_NAME, CSRF_COOKIE, client_ip, csrf_ok, csrf_token_for, rate_limiter
from app.web import core as web_core
from app.web.routers import routers as web_routers

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
    # The interactive API docs are for development only, not for public visitors.
    docs_url="/docs" if settings.env == "development" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.env == "development" else None,
)


@app.middleware("http")
async def security_and_limits(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/auth/login") or path.startswith("/api/auth/register"):
        bucket, limit = "auth", settings.rate_limit_auth
    elif path.startswith("/api/auth/guardian-consent") or (
            path.startswith(("/login", "/register", "/auth/", "/admin/login")) and request.method == "POST"):
        bucket, limit = "auth", settings.rate_limit_auth
    elif path.startswith("/api/assistant/messages"):
        bucket, limit = "assistant", settings.rate_limit_assistant
    else:
        bucket, limit = "default", settings.rate_limit_default
    if not rate_limiter.check(f"{bucket}:{client_ip(request)}", limit):
        return JSONResponse({"detail": "Too many requests — please wait a minute and try again."}, status_code=429)
    # Login/register start a new session, so a stale cookie must not block them. Guardian consent is protected
    # by its single-use emailed token instead (the guardian is usually not signed in).
    # The phone sign-in steps are protected by their own signed, short-lived cookie (no session exists yet).
    csrf_exempt = path in ("/api/auth/login", "/api/auth/register", "/login", "/register", "/register/google",
                           "/guardian-consent", "/login/phone", "/login/phone/signup", "/login/phone/resend",
                           "/login/phone/verify", "/admin/login")
    if not csrf_exempt and not csrf_ok(request):
        msg = "Security check failed (missing or invalid CSRF token). Reload the page and try again."
        if path.startswith("/api/"):
            return JSONResponse({"detail": msg}, status_code=403)
        return HTMLResponse(msg, status_code=403)
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


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # The assistant's voice input needs the microphone on this site only.
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(self), geolocation=()")
    if settings.cookie_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


# Pages and the exam room's OMR sheet are mostly repeated markup, so they compress well.
app.add_middleware(GZipMiddleware, minimum_size=1000)
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

# ---------------------------------------------------------------- website (Python: Jinja2 templates + HTMX)
app.mount("/static", StaticFiles(directory=web_core.WEB_DIR / "static"), name="static")
web_core.templates.env.globals["asset_version"] = int((web_core.WEB_DIR / "static/app.css").stat().st_mtime)
for r in web_routers:
    app.include_router(r)


@app.exception_handler(web_core.LoginRequired)
async def login_required(request: Request, exc: web_core.LoginRequired):
    # Admin pages send people to the admin sign-in; everything else to the student sign-in.
    target = "/admin/login" if exc.next_url.startswith("/admin") else f"/login?next={quote(exc.next_url)}"
    if request.headers.get("hx-request") == "true":
        return Response(status_code=204, headers={"HX-Redirect": target})
    return RedirectResponse(target, status_code=303)


@app.exception_handler(web_core.GuardianPending)
async def guardian_pending(request: Request, _exc):
    return web_core.templates.TemplateResponse(request, "errors/guardian_pending.html", {
        "page": web_core.Page(request, None, None), "me": None}, status_code=403)


@app.exception_handler(web_core.AdminRequired)
async def admin_required(request: Request, _exc):
    # Signed in, but not as an admin: offer the admin sign-in rather than a bare error.
    if request.headers.get("hx-request") == "true":
        return Response(status_code=204, headers={"HX-Redirect": "/admin/login"})
    return RedirectResponse("/admin/login", status_code=303)


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
