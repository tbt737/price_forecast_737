"""Application settings — resolved from the environment, never hardcoded.

Secrets/credentials come from environment variables (optionally via a local
``.env`` at the repo root). No connection string is baked into source.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# repo root = apps/api/app/core/config.py -> parents[4]
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PROFILES_DIR = REPO_ROOT / "configs" / "commodities"


class Settings(BaseSettings):
    """Runtime configuration. Reads env vars (case-insensitive) and repo-root .env."""

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Database — DATABASE_URL takes precedence; otherwise assembled from POSTGRES_*.
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    postgres_host: str | None = Field(default=None, alias="POSTGRES_HOST")
    postgres_port: str | None = Field(default=None, alias="POSTGRES_PORT")
    postgres_db: str | None = Field(default=None, alias="POSTGRES_DB")
    postgres_user: str | None = Field(default=None, alias="POSTGRES_USER")
    postgres_password: str | None = Field(default=None, alias="POSTGRES_PASSWORD")

    # API
    api_env: str = Field(default="development", alias="API_ENV")
    log_level: str = Field(default="info", alias="LOG_LEVEL")

    profiles_dir: Path = DEFAULT_PROFILES_DIR

    def resolved_database_url(self, default: str | None = None) -> str:
        """Return a usable SQLAlchemy URL or raise — never silently fabricate one."""
        if self.database_url:
            return self.database_url
        parts = (
            self.postgres_user,
            self.postgres_password,
            self.postgres_host,
            self.postgres_port,
            self.postgres_db,
        )
        if all(parts):
            return (
                f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        if default is not None:
            return default
        raise RuntimeError(
            "DATABASE_URL is not set and POSTGRES_* parts are incomplete. "
            "Copy .env.example to .env and fill in the connection details."
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Cached settings accessor (FastAPI dependency-friendly)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
