"""Tests for notification decision logic with time-machine."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import time_machine

from tests.conftest import make_direct_flight, make_query
from flight_alert_scraper.db.tables import AlertState
from flight_alert_scraper.engine.diffing import results_fingerprint
from flight_alert_scraper.engine.ranking import rank
from flight_alert_scraper.models.alert import AlertKind, SuppressReason, TriggerReason
from flight_alert_scraper.notifications.decide import decide

_NOW = datetime(2026, 12, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_state(ranked, last_digest=None, last_immediate=None) -> AlertState:
    import json
    fp = results_fingerprint(ranked)
    sigs = [m.option.signature for m in ranked.tier1]
    best = ranked.tier1[0] if ranked.tier1 else None
    return AlertState(
        query_key="test",
        results_fingerprint=fp,
        best_tier1_signature=best.option.signature if best else None,
        best_tier1_price_usd=best.option.price_usd if best else None,
        best_effective_cost_usd=best.effective_cost_usd if best else None,
        known_tier1_signatures=json.dumps(sigs),
        last_immediate_sent_at=last_immediate,
        last_digest_sent_at=last_digest,
        last_suppressed_reason=None,
        updated_at=_NOW,
    )


def _rank(flights, max_price="1200", max_duration=1320):
    query = make_query(max_price=max_price, max_duration=max_duration)
    return rank(flights, query)


def test_unchanged_results_suppressed():
    f = make_direct_flight("1100", 1200)
    ranked = _rank([f])
    state = _make_state(ranked)
    decision = decide(ranked, state, _NOW)
    assert not decision.should_send
    assert decision.suppress_reason == SuppressReason.UNCHANGED


def test_new_tier1_fires_immediate():
    f = make_direct_flight("1100", 1200)
    ranked = _rank([f])
    # state has no known_tier1_signatures
    state = _make_state(ranked)
    import json
    state.known_tier1_signatures = json.dumps([])
    state.results_fingerprint = "different"
    decision = decide(ranked, state, _NOW)
    assert decision.should_send
    assert decision.kind == AlertKind.IMMEDIATE
    assert decision.trigger_reason == TriggerReason.NEW_TIER1


def test_price_drop_5pct_fires_immediate():
    f = make_direct_flight("1040", 1200)
    ranked = _rank([f])
    sig = ranked.tier1[0].option.signature
    import json
    state = AlertState(
        query_key="test",
        results_fingerprint="old_fp",
        best_tier1_signature=sig,
        best_tier1_price_usd=Decimal("1100"),  # was $1100, now $1040 = -5.5%
        best_effective_cost_usd=Decimal("1500"),
        known_tier1_signatures=json.dumps([sig]),
        updated_at=_NOW,
    )
    decision = decide(ranked, state, _NOW)
    assert decision.should_send
    assert decision.trigger_reason == TriggerReason.PRICE_DROP_5PCT


def test_price_drop_4pct_stays_quiet():
    f = make_direct_flight("1057", 1200)
    ranked = _rank([f])
    sig = ranked.tier1[0].option.signature
    import json
    state = AlertState(
        query_key="test",
        results_fingerprint="old_fp",
        best_tier1_signature=sig,
        best_tier1_price_usd=Decimal("1100"),  # 3.9% drop
        best_effective_cost_usd=Decimal("1500"),
        known_tier1_signatures=json.dumps([sig]),
        updated_at=_NOW,
    )
    decision = decide(ranked, state, _NOW)
    assert not decision.should_send


def test_digest_fires_after_24h():
    f = make_direct_flight("1500", 1200)  # over budget
    ranked = _rank([f])
    last_digest = _NOW - timedelta(hours=25)
    state = _make_state(ranked, last_digest=last_digest)
    state.results_fingerprint = "different_fp"
    decision = decide(ranked, state, _NOW)
    assert decision.should_send
    assert decision.kind == AlertKind.DIGEST


def test_digest_suppressed_before_24h():
    f = make_direct_flight("1500", 1200)
    ranked = _rank([f])
    last_digest = _NOW - timedelta(hours=23, minutes=59)
    state = _make_state(ranked, last_digest=last_digest)
    state.results_fingerprint = "different_fp"
    decision = decide(ranked, state, _NOW)
    assert not decision.should_send
    assert decision.suppress_reason == SuppressReason.DIGEST_TOO_SOON


def test_empty_results_suppressed():
    query = make_query()
    ranked = rank([], query)
    decision = decide(ranked, None, _NOW)
    assert not decision.should_send
    assert decision.suppress_reason == SuppressReason.EMPTY_RESULTS


def test_four_unchanged_runs_at_most_one_email():
    """Simulate 4 consecutive runs with same data — should send on first, suppress rest."""
    f = make_direct_flight("1100", 1200)
    ranked = _rank([f])
    state = None
    send_count = 0
    for _ in range(4):
        decision = decide(ranked, state, _NOW)
        if decision.should_send:
            send_count += 1
        state = _make_state(ranked)
    assert send_count <= 1
