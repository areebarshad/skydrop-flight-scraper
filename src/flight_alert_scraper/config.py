from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from flight_alert_scraper.models.query import CabinClass, Constraints, SearchQuery


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    db_path: Path = Field(default=Path("./flight_alerts.db"))
    smtp_user: str = ""
    smtp_app_password: str = ""
    alert_recipient: str = ""
    serpapi_key: str = ""
    watchlist_path: Path = Field(default=Path("./watchlist.yaml"))
    dry_run: bool = False

    # Browser scraper knobs — change without code edits to bisect detection issues
    browser_headless: bool = True
    browser_block_assets: bool = True
    browser_channel: str = ""
    browser_wait_seconds: int = 90

    # Proxy — leave blank to disable
    proxy_url: str = ""
    proxy_pool: str = ""  # comma-separated list; takes precedence over proxy_url

    def load_queries(self) -> list[SearchQuery]:
        raw: dict[str, Any] = yaml.safe_load(self.watchlist_path.read_text())
        queries = []
        for entry in raw.get("queries", []):
            constraints = Constraints(**entry.pop("constraints"))
            cabin_raw = entry.pop("cabin", "economy")
            entry["cabin"] = CabinClass(cabin_raw)
            queries.append(SearchQuery(**entry, constraints=constraints))
        return queries


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
