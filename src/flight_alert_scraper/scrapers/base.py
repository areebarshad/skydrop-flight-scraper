"""Provider protocol and error taxonomy."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from flight_alert_scraper.models.flight import FlightOption
from flight_alert_scraper.models.query import SearchQuery


class ProviderError(Exception):
    pass


class TransientError(ProviderError):
    """Retry in place (e.g. 429, 5xx)."""


class BlockedError(ProviderError):
    """Consent wall / CAPTCHA — escalate to next provider."""


class ParseError(ProviderError):
    """HTML/JSON parse failed after retry — escalate."""


class ConfigError(ProviderError):
    """Bad configuration — fail loud, do not escalate."""


@runtime_checkable
class FlightProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def search(self, query: SearchQuery) -> list[FlightOption]: ...
