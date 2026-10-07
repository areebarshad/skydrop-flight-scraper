"""Fixture provider — replays saved flight options for testing. Never in the production chain."""
from __future__ import annotations

from flight_alert_scraper.models.flight import FlightOption
from flight_alert_scraper.models.query import SearchQuery


class FixtureProvider:
    name = "fixture"

    def __init__(self, flights: list[FlightOption]) -> None:
        self._flights = flights

    def available(self) -> bool:
        return True

    def search(self, query: SearchQuery) -> list[FlightOption]:
        return list(self._flights)
