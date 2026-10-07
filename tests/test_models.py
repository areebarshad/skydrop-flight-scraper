"""Tests for model validators."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from tests.conftest import make_direct_flight, make_links, make_query
from flight_alert_scraper.models.flight import BookingLinks, FlightOption, Layover, Leg
from flight_alert_scraper.models.query import CabinClass, Constraints, SearchQuery


def test_query_key_excludes_constraints():
    from datetime import date
    q1 = SearchQuery(
        origin="IAD", destination="KHI", depart_date=date(2026, 12, 1),
        cabin=CabinClass.ECONOMY, adults=1,
        constraints=Constraints(max_price_usd=Decimal("1200")),
    )
    q2 = SearchQuery(
        origin="IAD", destination="KHI", depart_date=date(2026, 12, 1),
        cabin=CabinClass.ECONOMY, adults=1,
        constraints=Constraints(max_price_usd=Decimal("800")),
    )
    assert q1.query_key == q2.query_key


def test_signature_excludes_price():
    f1 = make_direct_flight("1000.00", 1260)
    f2 = make_direct_flight("1500.00", 1260)
    assert f1.signature == f2.signature


def test_signature_changes_with_flight_number():
    f1 = make_direct_flight("1000.00", 1260, flight_num="785")
    f2 = make_direct_flight("1000.00", 1260, flight_num="786")
    assert f1.signature != f2.signature


def test_inconsistent_leg_chain_raises():
    now = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    arrive1 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    arrive2 = datetime(2026, 11, 1, 15, 0, tzinfo=timezone.utc)
    leg1 = Leg(
        carrier="A", carrier_code="AA", flight_number="1",
        origin="IAD", destination="DXB",
        depart_at=now, arrive_at=arrive1, duration_minutes=120,
    )
    leg2 = Leg(
        carrier="B", carrier_code="BB", flight_number="2",
        origin="LHR",  # doesn't chain from DXB
        destination="KHI",
        depart_at=arrive1, arrive_at=arrive2, duration_minutes=180,
    )
    layover = Layover(airport="DXB", duration_minutes=60)
    with pytest.raises(ValueError, match="destination"):
        FlightOption(
            legs=[leg1, leg2],
            layovers=[layover],
            price_usd=Decimal("1100"),
            total_duration_minutes=300,
            links=make_links(),
            source="test",
            scraped_at=now,
        )


def test_wrong_layover_count_raises():
    f = make_direct_flight("1000", 1260)
    now = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    arrive = datetime.fromtimestamp(now.timestamp() + 1260 * 60, tz=timezone.utc)
    leg = Leg(
        carrier="Test", carrier_code="PK", flight_number="785",
        origin="IAD", destination="KHI",
        depart_at=now, arrive_at=arrive, duration_minutes=1260,
    )
    extra_layover = Layover(airport="DXB", duration_minutes=90)
    with pytest.raises(ValueError, match="layovers"):
        FlightOption(
            legs=[leg],
            layovers=[extra_layover],
            price_usd=Decimal("1000"),
            total_duration_minutes=1260,
            links=make_links(),
            source="test",
            scraped_at=now,
        )


def test_duration_mismatch_raises():
    now = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    arrive = datetime.fromtimestamp(now.timestamp() + 1260 * 60, tz=timezone.utc)
    leg = Leg(
        carrier="Test", carrier_code="PK", flight_number="785",
        origin="IAD", destination="KHI",
        depart_at=now, arrive_at=arrive, duration_minutes=1260,
    )
    with pytest.raises(ValueError):
        FlightOption(
            legs=[leg],
            layovers=[],
            price_usd=Decimal("1000"),
            total_duration_minutes=21,  # 21 minutes vs 1260 — scaled by 60x
            links=make_links(),
            source="test",
            scraped_at=now,
        )
