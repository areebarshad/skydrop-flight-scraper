"""Table-driven tests for the tier ranking algorithm.

Covers every bullet from §3 'behaviors worth pinning'.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from tests.conftest import make_direct_flight, make_query
from flight_alert_scraper.engine.ranking import rank
from flight_alert_scraper.models.result import MatchLabel, Tier


def test_empty_options_all_tiers_empty():
    query = make_query()
    ranked = rank([], query)
    assert ranked.tier1 == []
    assert ranked.tier2 == []
    assert ranked.tier3 == []
    assert ranked.total_candidates == 0


def test_within_budget_and_time_goes_to_tier1():
    query = make_query(max_price="1200", max_duration=1320)
    f = make_direct_flight("1100", 1200)
    ranked = rank([f], query)
    assert len(ranked.tier1) == 1
    assert ranked.tier2 == []
    assert ranked.tier3 == []


def test_exact_boundary_price_is_tier1():
    query = make_query(max_price="1200", max_duration=1320)
    f = make_direct_flight("1200.00", 1320)
    ranked = rank([f], query)
    assert len(ranked.tier1) == 1


def test_over_budget_not_tier1():
    query = make_query(max_price="1200", max_duration=1320)
    f = make_direct_flight("1201.00", 1000)
    ranked = rank([f], query)
    assert ranked.tier1 == []


def test_no_time_limit_everything_within_budget_is_tier1():
    """max_duration_minutes is None → every within-budget flight is Tier 1."""
    query = make_query(max_price="1200", max_duration=None)
    f1 = make_direct_flight("1100", 2000)
    f2 = make_direct_flight("900", 3000)
    ranked = rank([f1, f2], query)
    assert len(ranked.tier1) == 2
    assert ranked.tier2 == []


def test_no_time_limit_value_deal_disabled():
    """Value Deal requires a time limit to exceed. With None it must not appear."""
    query = make_query(max_price="1200", max_duration=None)
    f = make_direct_flight("800", 1800)  # cheap but very long
    ranked = rank([f], query)
    assert len(ranked.tier1) == 1
    assert not any(MatchLabel.VALUE_DEAL in m.labels for m in ranked.tier2)


def test_value_deal_flight_in_tier1_not_double_reported():
    """A flight >= 20% under budget AND within time limit is Tier 1 only."""
    query = make_query(max_price="1200", max_duration=1320)
    f = make_direct_flight("900", 1200)  # 25% under budget, well within time
    ranked = rank([f], query)
    assert len(ranked.tier1) == 1
    assert ranked.tier2 == []


def test_value_deal_appears_in_tier2():
    """Over time limit by <= buffer, and >= 20% under budget."""
    query = make_query(max_price="1200", max_duration=1320)
    # 960 = 20% under 1200; 1440 = 120 min over 1320 (within 180 buffer)
    f = make_direct_flight("960.00", 1440)
    ranked = rank([f], query)
    assert ranked.tier1 == []
    assert len(ranked.tier2) == 1
    assert MatchLabel.VALUE_DEAL in ranked.tier2[0].labels


def test_time_saver_appears_in_tier2():
    """Within time limit, over budget by <= 10%."""
    query = make_query(max_price="1200", max_duration=1320)
    f = make_direct_flight("1300.00", 1200)  # 8.3% over budget, within time
    ranked = rank([f], query)
    assert ranked.tier1 == []
    assert len(ranked.tier2) == 1
    assert MatchLabel.TIME_SAVER in ranked.tier2[0].labels


def test_tier3_empty_when_tier1_has_matches():
    """Tier 3 stays empty whenever Tier 1 is non-empty."""
    query = make_query(max_price="1200", max_duration=1320)
    f = make_direct_flight("1100", 1200)
    ranked = rank([f], query)
    assert ranked.tier3 == []


def test_tier3_has_at_most_three_entries():
    """Tier 3: best_balance, cheapest, fastest — at most three, possibly overlapping."""
    query = make_query(max_price="1200", max_duration=1320)
    flights = [
        make_direct_flight("2000", 900, flight_num="F1"),  # expensive, fast
        make_direct_flight("1500", 1500, flight_num="F2"),  # cheap-ish, slow
        make_direct_flight("1800", 1000, flight_num="F3"),
    ]
    ranked = rank(flights, query)
    assert ranked.tier1 == []
    assert len(ranked.tier3) <= 3


def test_tier3_flight_can_have_multiple_labels():
    """A single flight can win best_balance, cheapest, and fastest."""
    query = make_query(max_price="100", max_duration=60)
    f = make_direct_flight("2000", 1500)  # the only option
    ranked = rank([f], query)
    assert ranked.tier1 == []
    assert len(ranked.tier3) == 1
    assert len(ranked.tier3[0].labels) == 3


def test_max_stops_hard_filter():
    """max_stops filters flights before anything else."""
    from datetime import datetime, timezone
    from flight_alert_scraper.models.flight import FlightOption, Layover, Leg
    from tests.conftest import make_links
    from flight_alert_scraper.models.query import CabinClass, Constraints, SearchQuery
    from datetime import date

    query = SearchQuery(
        origin="IAD", destination="KHI", depart_date=date(2026, 12, 1),
        cabin=CabinClass.ECONOMY, adults=1,
        constraints=Constraints(max_price_usd=Decimal("2000"), max_stops=0),
    )
    now = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    leg1 = Leg(carrier="A", carrier_code="AA", flight_number="1", origin="IAD", destination="DXB",
               depart_at=now, arrive_at=datetime.fromtimestamp(now.timestamp() + 600*60, tz=timezone.utc), duration_minutes=600)
    leg2 = Leg(carrier="A", carrier_code="AA", flight_number="2", origin="DXB", destination="KHI",
               depart_at=datetime.fromtimestamp(now.timestamp() + 660*60, tz=timezone.utc),
               arrive_at=datetime.fromtimestamp(now.timestamp() + 1080*60, tz=timezone.utc), duration_minutes=420)
    layover = Layover(airport="DXB", duration_minutes=60)
    one_stop = FlightOption(
        legs=[leg1, leg2], layovers=[layover],
        price_usd=Decimal("800"), total_duration_minutes=1080,
        links=make_links(), source="test",
        scraped_at=now,
    )
    direct = make_direct_flight("1800", 1260)  # direct but expensive

    ranked = rank([one_stop, direct], query)
    assert ranked.filtered_out == 1
    sigs_in_results = {m.option.signature for m in ranked.tier1 + ranked.tier2 + ranked.tier3}
    assert one_stop.signature not in sigs_in_results


def test_tier1_sorted_by_price():
    query = make_query(max_price="1200", max_duration=1320)
    f1 = make_direct_flight("1100", 1200, flight_num="F1")
    f2 = make_direct_flight("900", 1100, flight_num="F2")
    f3 = make_direct_flight("1050", 1300, flight_num="F3")
    ranked = rank([f1, f2, f3], query)
    prices = [m.option.price_usd for m in ranked.tier1]
    assert prices == sorted(prices)


def test_deduplication_keeps_cheapest():
    """Two options with same signature (same itinerary) — keep the cheaper price."""
    f1 = make_direct_flight("1100", 1200)
    f2 = make_direct_flight("1000", 1200)  # same itinerary, cheaper
    query = make_query(max_price="1200", max_duration=1320)
    ranked = rank([f1, f2], query)
    assert len(ranked.tier1) == 1
    assert ranked.tier1[0].option.price_usd == Decimal("1000")
