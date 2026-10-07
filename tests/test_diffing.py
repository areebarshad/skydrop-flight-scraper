"""Tests for diffing and fingerprinting."""
from __future__ import annotations

from decimal import Decimal

import pytest

from tests.conftest import make_direct_flight, make_query
from flight_alert_scraper.engine.diffing import (
    extract_prices,
    is_negligible_change_prices,
    is_new_tier1,
    is_price_drop,
    results_fingerprint,
)
from flight_alert_scraper.engine.ranking import rank


def _ranked_with_flights(flights, max_price="1200", max_duration=1320):
    query = make_query(max_price=max_price, max_duration=max_duration)
    return rank(flights, query)


def test_identical_results_same_fingerprint():
    f = make_direct_flight("1100", 1200)
    r1 = _ranked_with_flights([f])
    r2 = _ranked_with_flights([f])
    assert results_fingerprint(r1) == results_fingerprint(r2)


def test_price_change_changes_fingerprint():
    f1 = make_direct_flight("1100", 1200)
    f2 = make_direct_flight("1050", 1200)
    r1 = _ranked_with_flights([f1])
    r2 = _ranked_with_flights([f2])
    assert results_fingerprint(r1) != results_fingerprint(r2)


def test_negligible_change_within_threshold():
    sig = "abc123"
    new_prices = {sig: Decimal("1010")}
    old_prices = {sig: Decimal("1000")}
    assert is_negligible_change_prices(new_prices, old_prices, threshold_pct=Decimal("0.03"))


def test_negligible_change_exceeds_threshold():
    sig = "abc123"
    new_prices = {sig: Decimal("1050")}
    old_prices = {sig: Decimal("1000")}
    assert not is_negligible_change_prices(new_prices, old_prices, threshold_pct=Decimal("0.03"))


def test_negligible_change_different_sigs_not_negligible():
    new_prices = {"sig1": Decimal("1000")}
    old_prices = {"sig2": Decimal("1000")}
    assert not is_negligible_change_prices(new_prices, old_prices)


def test_is_new_tier1_detects_new_itinerary():
    f = make_direct_flight("1100", 1200)
    ranked = _ranked_with_flights([f])
    assert is_new_tier1(ranked, known_signatures=[])


def test_is_new_tier1_false_when_already_known():
    f = make_direct_flight("1100", 1200)
    ranked = _ranked_with_flights([f])
    sigs = [m.option.signature for m in ranked.tier1]
    assert not is_new_tier1(ranked, known_signatures=sigs)


def test_price_drop_detected():
    f = make_direct_flight("1000", 1200)
    ranked = _ranked_with_flights([f])
    sig = ranked.tier1[0].option.signature
    assert is_price_drop(ranked, sig, Decimal("1100"), threshold_pct=Decimal("0.05"))


def test_price_drop_below_threshold_not_detected():
    f = make_direct_flight("1060", 1200)
    ranked = _ranked_with_flights([f])
    sig = ranked.tier1[0].option.signature
    assert not is_price_drop(ranked, sig, Decimal("1100"), threshold_pct=Decimal("0.05"))
