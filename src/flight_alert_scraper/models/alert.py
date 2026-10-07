from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from flight_alert_scraper.models.result import RankedResults


class AlertKind(StrEnum):
    IMMEDIATE = "immediate"
    DIGEST = "digest"


class TriggerReason(StrEnum):
    NEW_TIER1 = "new_tier1"
    PRICE_DROP_5PCT = "price_drop_5pct"
    NO_TIER1_24H = "no_tier1_24h"


class SuppressReason(StrEnum):
    UNCHANGED = "unchanged"
    NEGLIGIBLE_CHANGE = "negligible_change"
    DIGEST_TOO_SOON = "digest_too_soon"
    EMPTY_RESULTS = "empty_results"


class AlertDecision(BaseModel):
    should_send: bool
    kind: AlertKind | None = None
    trigger_reason: TriggerReason | None = None
    suppress_reason: SuppressReason | None = None
    ranked: RankedResults
