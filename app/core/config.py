from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/project_elevate"

    # OpenAI (for embeddings + Step 1 classification)
    OPENAI_API_KEY: str

    # Anthropic (for inventor alignment reports — Step 3)
    ANTHROPIC_API_KEY: str = ""

    # ── Data source API keys (all free to obtain) ─────────────────────────────
    # CDC Socrata app token: https://data.cdc.gov/profile/app_tokens
    CDC_APP_TOKEN: str = ""

    # FDA API key: https://open.fda.gov/apis/authentication/
    FDA_API_KEY: str = ""

    # Census Bureau: https://api.census.gov/data/key_signup.html
    CENSUS_API_KEY: str = ""

    # HRSA: https://data.hrsa.gov/tools/web-services/registration
    HRSA_API_KEY: str = ""

    # ── Reddit API (for pain point scraping) ──────────────────────────────────
    # Create app at: https://www.reddit.com/prefs/apps
    # Choose "script" type. Use client_id and client_secret.
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USERNAME: str = ""   # optional, for user-agent

    # ── App ────────────────────────────────────────────────────────────────────
    # ── Auth ───────────────────────────────────────────────────────────────
    JWT_SECRET: str = "project-elevate-dev-secret-change-in-production"
    GOOGLE_CLIENT_ID: str = ""

    # ── Email (for weekly digests) ────────────────────────────────────────────
    EMAIL_HOST:     str = ""   # smtp.gmail.com
    EMAIL_PORT:     int = 587
    EMAIL_USER:     str = ""   # your@gmail.com
    EMAIL_PASSWORD: str = ""   # Gmail App Password
    EMAIL_FROM:     str = ""   # "Project Elevate <alerts@projectelevate.io>"
    GOOGLE_CLIENT_ID: str = ""  # optional — add your Google OAuth client ID

    DEBUG: bool = True
    ENVIRONMENT: str = "development"

    # Whether to start the ingestion scheduler on app startup
    # Set to False during development to avoid background jobs
    ENABLE_SCHEDULER: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_file_override = False
        case_sensitive = False

@lru_cache()
def get_settings():
    return Settings()

settings = get_settings()
