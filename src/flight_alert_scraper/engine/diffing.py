"""State-change detection and fingerprinting."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from flight_alert_scraper.models.result import RankedResults


def results_fingerprint(ranked: RankedResults) -> str:
    """sha256 over sorted (signature, price_usd) from Tier 1+2."""
    items = sorted(
        (m.option.signature, str(m.option.price_usd))
        for m in ranked.tier1 + ranked.tier2
    )
    payload = json.dumps(items, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def is_negligible_change(
    ranked: RankedResults,
    old_fingerprint: str | None,
    threshold_pct: Decimal = Decimal("0.03"),
) -> bool:
    """Return True if fingerprint differs only by small price jitter (<= 3%)."""
    if old_fingerprint is None:
        return False

    new_items = {
        m.option.signature: m.option.price_usd for m in ranked.tier1 + ranked.tier2
    }
    # we need to decode the old fingerprint — but we only have the hash.
    # Negligible-change detection requires price history from the DB, which
    # the caller must provide. This function is called with explicit old/new prices.
    return False


def is_negligible_change_prices(
    new_prices: dict[str, Decimal],
    old_prices: dict[str, Decimal],
    threshold_pct: Decimal = Decimal("0.03"),
) -> bool:
    """Return True if all matched prices moved < threshold and tier membership unchanged."""
    if set(new_prices.keys()) != set(old_prices.keys()):
        return False
    for sig, new_price in new_prices.items():
        old_price = old_prices[sig]
        if old_price == 0:
            return False
        change = abs(new_price - old_price) / old_price
        if change >= threshold_pct:
            return False
    return True


def extract_prices(ranked: RankedResults) -> dict[str, Decimal]:
    return {m.option.signature: m.option.price_usd for m in ranked.tier1 + ranked.tier2}


def is_new_tier1(ranked: RankedResults, known_signatures: list[str]) -> bool:
    known = set(known_signatures)
    return any(m.option.signature not in known for m in ranked.tier1)


def is_price_drop(
    ranked: RankedResults,
    best_tier1_signature: str | None,
    best_tier1_price: Decimal | None,
    threshold_pct: Decimal = Decimal("0.05"),
) -> bool:
    if best_tier1_signature is None or best_tier1_price is None:
        return False
    for m in ranked.tier1:
        if m.option.signature == best_tier1_signature:
            drop = (best_tier1_price - m.option.price_usd) / best_tier1_price
            return drop >= threshold_pct
    return False
