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

    # App
    DEBUG:            bool = True
    ENVIRONMENT:      str  = "development"
    ENABLE_SCHEDULER: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


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
    if not s.OPENAI_API_KEY:
        s.OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    if not s.DATABASE_URL or "localhost" in s.DATABASE_URL:
        db = os.environ.get("DATABASE_URL", "")
        if db:
            s.DATABASE_URL = db
    return s


settings = get_settings()
