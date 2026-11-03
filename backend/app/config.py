"""Application settings. All secrets come from environment variables (see .env.example)."""
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DEV_JWT_SECRET = "dev-only-insecure-secret-change-me-in-env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    env: str = "development"
    database_url: str = f"sqlite:///{(BASE_DIR / 'neet_dev.db').as_posix()}"
    jwt_secret: str = DEV_JWT_SECRET
    jwt_expiry_minutes: int = 60 * 24
    cookie_secure: bool = False
    storage_dir: Path = BASE_DIR / "storage"
    cors_origins: list[str] = []  # the website is served by this app, so no other origin needs access
    # Public URL of the web app, used in emailed links (guardian consent).
    public_app_url: str = "http://localhost:8000"
    log_json: bool = False

    # Rate limits: requests per minute per client IP. Set REDIS_URL to share counts across workers.
    rate_limit_default: int = 240
    rate_limit_auth: int = 20
    rate_limit_assistant: int = 30
    redis_url: str = ""
    # Only enable behind a reverse proxy you control; otherwise clients can spoof their IP.
    trust_proxy_headers: bool = False

    # LLM provider: "openrouter" or "anthropic". No key for the chosen provider => deterministic,
    # tool-only assistant.
    llm_provider: str = "openrouter"
    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-5-5"
    openrouter_api_key: str = ""
    # Fast, cheap and reliable at tool calling; tried in order if a provider is down.
    openrouter_model: str = "anthropic/claude-haiku-5.5"
    openrouter_fallback_models: list[str] = ["google/gemini-2.5-flash-lite", "openai/gpt-4.1-nano"]

    # Practice question bank: AI-written questions, kept only when an independent model gets the same answer.
    # Each student only ever sees questions they have not seen before; the bank is topped up automatically.
    question_gen_enabled: bool = True
    question_writer_model: str = "anthropic/claude-haiku-5.5"
    question_checker_model: str = "deepseek/deepseek-v4-flash"  # different provider, so mistakes don't line up
    question_gen_workers: int = 6
    unseen_buffer_per_section: int = 60  # top up when a student has fewer unseen questions than this

    # Semantic search. Empty key => BM25 keyword ranking only.
    embedding_provider: str = "voyage"
    voyage_api_key: str = ""
    embedding_model: str = "voyage-3.5"

    # OCR for scanned PDFs (needs the Tesseract binary; Docker image installs it).
    ocr_enabled: bool = True
    tesseract_cmd: str = ""
    ocr_languages: str = "eng"

    # Nearby places. "none" or "overpass" (OpenStreetMap data, ODbL, attribution required).
    places_provider: str = "none"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    places_user_agent: str = "NEETCompass/0.2 (admin-triggered refresh; contact: set PLACES_USER_AGENT)"
    # Map tiles on the "Around campus" tab. tile.openstreetmap.org is for light use only; set your provider in production.
    map_tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    map_attribution: str = "© OpenStreetMap contributors"

    # Email (guardian consent links). "console" logs the email instead of sending it.
    email_backend: str = "console"
    email_from: str = "no-reply@example.invalid"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True

    # Privacy / DPDP
    privacy_notice_version: str = "2026-11-b"
    # Shown on the privacy policy and terms pages (and needed by Google's sign-in branding).
    contact_email: str = ""
    # Phone sign-in with an SMS code, through Tekurious AI-Auth (server-side only; never sent to browsers).
    tekurious_api_key: str = ""
    tekurious_base_url: str = "https://api.tekurious.si"
    otp_resend_seconds: int = 45
    # In Tekurious's test ("stub") mode no SMS is sent and a fixed code works for any number, so anyone could sign
    # in as anyone. Refuse such sign-ins unless this is switched on deliberately for testing.
    phone_allow_stub: bool = False
    # Google sign-in (OAuth client from Google Cloud Console → APIs & Services → Credentials).
    google_client_id: str = ""
    google_client_secret: str = ""
    # Where Google sends people back. Empty: <PUBLIC_APP_URL>/auth/google/callback. Set it when the site's address
    # changes (a Cloudflare quick tunnel), to a fixed page that forwards to the current address.
    google_redirect_uri: str = ""
    # Sign-in history shown to admins; older rows are deleted by the daily purge job.
    login_history_days: int = 180
    guardian_link_hours: int = 72
    unconsented_minor_retention_days: int = 7
    # Reference to the completed legal review (ticket, memo id). Empty = not done; shown on /admin readiness.
    dpdp_review_reference: str = ""

    # Predictor defaults
    predictor_years_considered: int = 3

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, v: str) -> str:
        """Hosted Postgres (Neon, Supabase, Render) hands out postgres:// URLs; SQLAlchemy needs the driver named."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @property
    def phone_enabled(self) -> bool:
        return bool(self.tekurious_api_key)

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def llm_configured(self) -> bool:
        return bool(self.openrouter_api_key if self.llm_provider == "openrouter" else self.anthropic_api_key)

    @model_validator(mode="after")
    def production_guards(self):
        if self.env == "production":
            problems = []
            if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
                problems.append("JWT_SECRET must be a random string of 32+ characters")
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true (serve over HTTPS)")
            if self.database_url.startswith("sqlite"):
                problems.append("DATABASE_URL must point to PostgreSQL")
            if self.email_backend == "console":
                problems.append("EMAIL_BACKEND must be smtp (guardian consent emails)")
            if problems:
                raise ValueError("Refusing to start in production: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
