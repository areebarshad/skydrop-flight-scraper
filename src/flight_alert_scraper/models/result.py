from __future__ import annotations

from decimal import Decimal
from enum import IntEnum, StrEnum

from pydantic import BaseModel

from flight_alert_scraper.models.flight import FlightOption
from flight_alert_scraper.models.query import SearchQuery


class Tier(IntEnum):
    DIRECT_MATCH = 1
    NEAR_MISS = 2
    BASELINE = 3


class MatchLabel(StrEnum):
    DIRECT = "direct_match"
    VALUE_DEAL = "value_deal"
    TIME_SAVER = "time_saver"
    BEST_BALANCE = "best_balance"
    CHEAPEST = "cheapest"
    FASTEST = "fastest"


class TieredMatch(BaseModel):
    model_config = {"frozen": True}

    option: FlightOption
    tier: Tier
    labels: list[MatchLabel]
    effective_cost_usd: Decimal
    price_delta_usd: Decimal
    duration_delta_minutes: int
    tradeoff_note: str


class RankedResults(BaseModel):
    query: SearchQuery
    tier1: list[TieredMatch]
    tier2: list[TieredMatch]
    tier3: list[TieredMatch]
    total_candidates: int
    filtered_out: int

    @property
    def has_direct_match(self) -> bool:
        return len(self.tier1) > 0

    @property
    def best(self) -> TieredMatch | None:
        if self.tier1:
            return self.tier1[0]
        if self.tier2:
            return self.tier2[0]
        if self.tier3:
            return self.tier3[0]
        return None
