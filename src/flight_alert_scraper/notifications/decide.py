"""Alert trigger logic. Pure function — no I/O, fully unit-testable with time-machine."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flight_alert_scraper.db.tables import AlertState
from flight_alert_scraper.engine.diffing import (
    extract_prices,
    is_negligible_change_prices,
    is_new_tier1,
    is_price_drop,
    results_fingerprint,
)
from flight_alert_scraper.models.alert import AlertDecision, AlertKind, SuppressReason, TriggerReason
from flight_alert_scraper.models.result import RankedResults

_DIGEST_INTERVAL = timedelta(hours=24)


def decide(
    ranked: RankedResults,
    state: AlertState | None,
    now: datetime,
) -> AlertDecision:
    import json

    if not ranked.tier1 and not ranked.tier2 and not ranked.tier3:
        return AlertDecision(
            should_send=False,
            suppress_reason=SuppressReason.EMPTY_RESULTS,
            ranked=ranked,
        )

    new_fp = results_fingerprint(ranked)

    if state is not None and state.results_fingerprint == new_fp:
        return AlertDecision(
            should_send=False,
            suppress_reason=SuppressReason.UNCHANGED,
            ranked=ranked,
        )

    known_sigs: list[str] = []
    if state and state.known_tier1_signatures:
        try:
            known_sigs = json.loads(state.known_tier1_signatures)
        except Exception:
            known_sigs = []

    best_sig = state.best_tier1_signature if state else None
    best_price = state.best_tier1_price_usd if state else None

    # New itinerary in Tier 1 always fires immediately.
    if ranked.tier1 and is_new_tier1(ranked, known_sigs):
        return AlertDecision(
            should_send=True,
            kind=AlertKind.IMMEDIATE,
            trigger_reason=TriggerReason.NEW_TIER1,
            ranked=ranked,
        )

    # Price drop on the same itinerary fires immediately.
    if ranked.tier1 and is_price_drop(ranked, best_sig, best_price):
        return AlertDecision(
            should_send=True,
            kind=AlertKind.IMMEDIATE,
            trigger_reason=TriggerReason.PRICE_DROP_5PCT,
            ranked=ranked,
        )

    # Suppress small jitter after the above immediate triggers.
    if state is not None and state.results_fingerprint is not None:
        new_prices = extract_prices(ranked)
        old_state_prices: dict[str, Decimal] = {}
        if state.best_tier1_signature and state.best_tier1_price_usd:
            old_state_prices[state.best_tier1_signature] = state.best_tier1_price_usd

        if new_prices and old_state_prices:
            common = {k: v for k, v in new_prices.items() if k in old_state_prices}
            old_common = {k: old_state_prices[k] for k in common}
            if common and is_negligible_change_prices(common, old_common):
                return AlertDecision(
                    should_send=False,
                    suppress_reason=SuppressReason.NEGLIGIBLE_CHANGE,
                    ranked=ranked,
                )

    if not ranked.tier1:
        last_digest = state.last_digest_sent_at if state else None
        if last_digest is None or (now - last_digest) >= _DIGEST_INTERVAL:
            return AlertDecision(
                should_send=True,
                kind=AlertKind.DIGEST,
                trigger_reason=TriggerReason.NO_TIER1_24H,
                ranked=ranked,
            )
        return AlertDecision(
            should_send=False,
            suppress_reason=SuppressReason.DIGEST_TOO_SOON,
            ranked=ranked,
        )

    return AlertDecision(
        should_send=False,
        suppress_reason=SuppressReason.UNCHANGED,
        ranked=ranked,
    )
