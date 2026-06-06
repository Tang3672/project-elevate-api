import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/project_elevate"

    # OpenAI (for embeddings + classification)
    OPENAI_API_KEY: str = ""

    # Anthropic (for PI reports)
    ANTHROPIC_API_KEY: str = ""

    # Data source API keys
    CDC_APP_TOKEN:    str = ""
    FDA_API_KEY:      str = ""
    CENSUS_API_KEY:   str = ""
    HRSA_API_KEY:     str = ""

    # Reddit
    REDDIT_CLIENT_ID:     str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USERNAME:      str = ""

    # Auth
    JWT_SECRET:       str = "project-elevate-dev-secret-change-in-production"
    GOOGLE_CLIENT_ID: str = ""

    # Email
    EMAIL_HOST:     str = ""
    EMAIL_PORT:     int = 587
    EMAIL_USER:     str = ""
    EMAIL_PASSWORD: str = ""
    EMAIL_FROM:     str = ""
    SMTP_HOST:      str = ""
    SMTP_PORT:      int = 587
    SMTP_USER:      str = ""
    SMTP_PASS:      str = ""

    # App
    DEBUG:            bool = True
    ENVIRONMENT:      str  = "development"
    ENABLE_SCHEDULER: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


    # ── Stripe Billing ────────────────────────────────────────────────────────
    SMTP_PASS: str = ""
    STRIPE_SECRET_KEY:     str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_ID:       str = ""
    STRIPE_BASIC_PRICE_ID:  str = ""
    STRIPE_PRO_PRICE_ID:    str = ""


def get_settings() -> Settings:
    s = Settings()
    # Hard override from os.environ — fixes Railway where .env doesn't exist
    if not s.ANTHROPIC_API_KEY:
        # Also check for key with trailing space (Railway UI bug)
        s.ANTHROPIC_API_KEY = (
            os.environ.get("ANTHROPIC_API_KEY") or
            os.environ.get("ANTHROPIC_API_KEY ") or
            ""
        ).strip()

    # Scan all env vars for Stripe keys (handles trailing space Railway bug)
    for k, v in os.environ.items():
        if k.strip() == "STRIPE_SECRET_KEY" and v.strip():
            s.STRIPE_SECRET_KEY = v.strip()
        if k.strip() == "STRIPE_WEBHOOK_SECRET" and v.strip():
            s.STRIPE_WEBHOOK_SECRET = v.strip()
        if k.strip() == "STRIPE_PRICE_ID" and v.strip():
            s.STRIPE_PRICE_ID = v.strip()
    if not s.OPENAI_API_KEY:
        s.OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    if not s.SMTP_HOST:
        s.SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
    if not s.SMTP_USER:
        s.SMTP_USER = os.environ.get("SMTP_USER", "").strip()
    if not s.SMTP_PASS:
        s.SMTP_PASS = os.environ.get("SMTP_PASS", "").strip()
    if not s.EMAIL_FROM:
        s.EMAIL_FROM = os.environ.get("EMAIL_FROM", "").strip()
    if not s.SMTP_PORT:
        s.SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    if not s.DATABASE_URL or "localhost" in s.DATABASE_URL:
        db = os.environ.get("DATABASE_URL", "")
        if db:
            s.DATABASE_URL = db
    return s


settings = get_settings()

# Last resort: directly patch from env if still empty
import os as _final_os
if not settings.ANTHROPIC_API_KEY:
    for _k, _v in _final_os.environ.items():
        if _k.strip() == "ANTHROPIC_API_KEY" and _v.strip():
            settings.ANTHROPIC_API_KEY = _v.strip()
            break
