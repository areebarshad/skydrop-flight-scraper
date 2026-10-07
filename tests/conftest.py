"""Shared fixtures for all tests."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from flight_alert_scraper.models.flight import BookingLinks, FlightOption, Layover, Leg
from flight_alert_scraper.models.query import CabinClass, Constraints, SearchQuery


def make_links() -> BookingLinks:
    return BookingLinks(
        google_search="https://www.google.com/travel/flights",
        kayak_search="https://www.kayak.com/flights/IAD-KHI",
    )


def make_direct_flight(
    price: str,
    duration_minutes: int,
    carrier_code: str = "PK",
    flight_num: str = "785",
) -> FlightOption:
    now = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
    arrive = datetime.fromtimestamp(now.timestamp() + duration_minutes * 60, tz=timezone.utc)
    leg = Leg(
        carrier="Test Airline",
        carrier_code=carrier_code,
        flight_number=flight_num,
        origin="IAD",
        destination="KHI",
        depart_at=now,
        arrive_at=arrive,
        duration_minutes=duration_minutes,
    )
    return FlightOption(
        legs=[leg],
        layovers=[],
        price_usd=Decimal(price),
        total_duration_minutes=duration_minutes,
        links=make_links(),
        source="fixture",
        scraped_at=now,
    )


def make_query(
    max_price: str = "1200.00",
    max_duration: int | None = 1320,
) -> SearchQuery:
    from datetime import date
    return SearchQuery(
        origin="IAD",
        destination="KHI",
        depart_date=date(2026, 12, 1),
        cabin=CabinClass.ECONOMY,
        adults=1,
        constraints=Constraints(
            max_price_usd=Decimal(max_price),
            max_duration_minutes=max_duration,
        ),
    )
