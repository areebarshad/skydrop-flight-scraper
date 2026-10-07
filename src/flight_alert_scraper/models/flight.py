from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, computed_field, model_validator

from flight_alert_scraper.models.query import AirportCode


class BookingLinks(BaseModel):
    google_search: str
    kayak_search: str
    airline_direct: str | None = None


class Leg(BaseModel):
    model_config = {"frozen": True}

    carrier: str
    carrier_code: str
    flight_number: str
    origin: AirportCode
    destination: AirportCode
    depart_at: datetime
    arrive_at: datetime
    duration_minutes: int
    aircraft: str | None = None


class Layover(BaseModel):
    model_config = {"frozen": True}

    airport: AirportCode
    duration_minutes: int
    overnight: bool = False
    changes_airport: bool = False


class FlightOption(BaseModel):
    model_config = {"frozen": True}

    legs: list[Leg] = Field(min_length=1)
    layovers: list[Layover] = Field(default_factory=list)
    price_usd: Decimal
    total_duration_minutes: int
    links: BookingLinks
    source: str
    scraped_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def stops(self) -> int:
        return len(self.layovers)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def signature(self) -> str:
        parts = []
        for leg in self.legs:
            parts.append(
                f"{leg.carrier_code}{leg.flight_number}"
                f"@{leg.depart_at.isoformat()}>{leg.arrive_at.isoformat()}"
            )
        payload = json.dumps(parts)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    @model_validator(mode="after")
    def _check_consistency(self) -> "FlightOption":
        if len(self.layovers) != len(self.legs) - 1:
            raise ValueError(
                f"Expected {len(self.legs) - 1} layovers for {len(self.legs)} legs, "
                f"got {len(self.layovers)}"
            )
        for i in range(len(self.legs) - 1):
            if self.legs[i].destination != self.legs[i + 1].origin:
                raise ValueError(
                    f"Leg {i} destination {self.legs[i].destination} != "
                    f"leg {i+1} origin {self.legs[i+1].origin}"
                )
        if len(self.legs) > 0:
            computed = int(
                (self.legs[-1].arrive_at - self.legs[0].depart_at).total_seconds() / 60
            )
            if abs(computed - self.total_duration_minutes) > 2:
                raise ValueError(
                    f"total_duration_minutes {self.total_duration_minutes} differs "
                    f"from computed {computed} by more than 2 minutes"
                )
        return self
