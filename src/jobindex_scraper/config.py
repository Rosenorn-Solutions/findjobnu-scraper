from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
)


@dataclass(frozen=True)
class Settings:
    user_agent: str
    http_timeout_seconds: float
    log_level: str
    database_url: str | None
    extraction_version: str

    def config_fingerprint(self) -> str:
        payload = json.dumps(
            {
                "database_enabled": bool(self.database_url),
                "extraction_version": self.extraction_version,
                "http_timeout_seconds": self.http_timeout_seconds,
                "log_level": self.log_level,
                "user_agent": self.user_agent,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_settings() -> Settings:
    return Settings(
        user_agent=os.getenv("JOBINDEX_SCRAPER_USER_AGENT", DEFAULT_USER_AGENT),
        http_timeout_seconds=float(
            os.getenv("JOBINDEX_SCRAPER_HTTP_TIMEOUT_SECONDS", "20")
        ),
        log_level=os.getenv("JOBINDEX_SCRAPER_LOG_LEVEL", "INFO").upper(),
        database_url=_optional_env("JOBINDEX_SCRAPER_DATABASE_URL"),
        extraction_version=os.getenv("JOBINDEX_SCRAPER_EXTRACTION_VERSION", "dev"),
    )


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
