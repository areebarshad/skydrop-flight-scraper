"""ProviderChain: ordered failover across FlightProvider implementations."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from flight_alert_scraper.models.flight import FlightOption
from flight_alert_scraper.models.query import SearchQuery
from flight_alert_scraper.scrapers.base import (
    BlockedError,
    ConfigError,
    FlightProvider,
    ParseError,
    ProviderError,
    TransientError,
)

log = logging.getLogger(__name__)


@dataclass
class ProviderResult:
    provider: str
    results: list[FlightOption]
    error: str | None = None


@dataclass
class ChainMetrics:
    attempts: list[ProviderResult] = field(default_factory=list)

    @property
    def serving_provider(self) -> str | None:
        for r in self.attempts:
            if r.results:
                return r.provider
        return None


class ProviderChain:
    def __init__(self, providers: list[FlightProvider]) -> None:
        self._providers = providers

    def search(self, query: SearchQuery) -> tuple[list[FlightOption], ChainMetrics]:
        metrics = ChainMetrics()

        for provider in self._providers:
            if not provider.available():
                log.debug("Provider %s not available, skipping", provider.name)
                continue

            log.info("Trying provider: %s", provider.name)
            try:
                results = provider.search(query)
                metrics.attempts.append(ProviderResult(provider=provider.name, results=results))
                log.info("Provider %s returned %d results", provider.name, len(results))
                return results, metrics
            except ConfigError as exc:
                log.error("Provider %s config error: %s", provider.name, exc)
                metrics.attempts.append(
                    ProviderResult(provider=provider.name, results=[], error=str(exc))
                )
                raise
            except (BlockedError, ParseError) as exc:
                log.warning("Provider %s escalating: %s", provider.name, exc)
                metrics.attempts.append(
                    ProviderResult(provider=provider.name, results=[], error=str(exc))
                )
            except TransientError as exc:
                log.warning("Provider %s transient error: %s", provider.name, exc)
                metrics.attempts.append(
                    ProviderResult(provider=provider.name, results=[], error=str(exc))
                )
            except ProviderError as exc:
                log.warning("Provider %s error: %s", provider.name, exc)
                metrics.attempts.append(
                    ProviderResult(provider=provider.name, results=[], error=str(exc))
                )

        log.error("All providers exhausted for %s->%s", query.origin, query.destination)
        return [], metrics
