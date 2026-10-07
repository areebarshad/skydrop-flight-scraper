from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, computed_field, model_validator

AirportCode = Annotated[str, Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")]


class CabinClass(StrEnum):
    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"


class TripType(StrEnum):
    ONE_WAY = "one_way"
    ROUND_TRIP = "round_trip"


class Constraints(BaseModel):
    model_config = {"frozen": True}

    max_price_usd: Decimal
    max_duration_minutes: int | None = None
    max_stops: int | None = None
    value_deal_discount: Decimal = Decimal("0.20")
    value_deal_duration_buffer_minutes: int = 180
    time_saver_price_overage: Decimal = Decimal("0.10")
    hourly_time_penalty_usd: Decimal = Decimal("20.00")


class SearchQuery(BaseModel):
    model_config = {"frozen": True}

    origin: AirportCode
    destination: AirportCode
    depart_date: date
    return_date: date | None = None
    cabin: CabinClass = CabinClass.ECONOMY
    adults: int = Field(default=1, ge=1)
    constraints: Constraints

    @computed_field  # type: ignore[prop-decorator]
    @property
    def query_key(self) -> str:
        payload = json.dumps(
            {
                "origin": self.origin,
                "destination": self.destination,
                "depart_date": self.depart_date.isoformat(),
                "return_date": self.return_date.isoformat() if self.return_date else None,
                "cabin": self.cabin,
                "adults": self.adults,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    @model_validator(mode="after")
    def _check_dates(self) -> "SearchQuery":
        if self.return_date is not None and self.return_date < self.depart_date:
            raise ValueError("return_date must be >= depart_date")
        return self
