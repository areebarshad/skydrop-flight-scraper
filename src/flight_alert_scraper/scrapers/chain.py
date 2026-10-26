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
    NoResultsError,
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
    error_type: str | None = None  # "no_results", "transient", "blocked", etc.


@dataclass
class ChainMetrics:
    attempts: list[ProviderResult] = field(default_factory=list)

    @property
    def serving_provider(self) -> str | None:
        for r in self.attempts:
            if r.results:
                return r.provider
        return None

    @property
    def outcome(self) -> str:
        """Derive run outcome: 'ok', 'no_results', or 'failed'."""
        if any(r.results for r in self.attempts):
            return "ok"
        ran = [r for r in self.attempts if r.results or r.error is not None]
        if ran and all(r.error_type == "no_results" for r in ran):
            return "no_results"
        return "failed"


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
                if not results:
                    log.warning(
                        "Provider %s returned 0 results, trying next",
                        provider.name,
                    )
                    metrics.attempts.append(
                        ProviderResult(
                            provider=provider.name,
                            results=[],
                            error="returned 0 results",
                        )
                    )
                    continue
                metrics.attempts.append(
                    ProviderResult(provider=provider.name, results=results)
                )
                log.info("Provider %s returned %d results", provider.name, len(results))
                return results, metrics
            except ConfigError as exc:
                log.error("Provider %s config error: %s", provider.name, exc)
                metrics.attempts.append(
                    ProviderResult(provider=provider.name, results=[], error=str(exc))
                )
                raise
            except NoResultsError as exc:
                log.warning("Provider %s no results: %s", provider.name, exc)
                metrics.attempts.append(
                    ProviderResult(
                        provider=provider.name,
                        results=[],
                        error=str(exc),
                        error_type="no_results",
                    )
                )
            except (BlockedError, ParseError) as exc:
                log.warning("Provider %s escalating: %s", provider.name, exc)
                metrics.attempts.append(
                    ProviderResult(provider=provider.name, results=[], error=str(exc))
                )
            except TransientError as exc:
                log.warning("Provider %s transient error: %s", provider.name, exc)
                metrics.attempts.append(
                    ProviderResult(
                        provider=provider.name,
                        results=[],
                        error=str(exc),
                        error_type="transient",
                    )
                )
            except ProviderError as exc:
                log.warning("Provider %s error: %s", provider.name, exc)
                metrics.attempts.append(
                    ProviderResult(provider=provider.name, results=[], error=str(exc))
                )

        log.error("All providers exhausted for %s->%s", query.origin, query.destination)
        return [], metrics
