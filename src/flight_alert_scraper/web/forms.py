from __future__ import annotations

import datetime as dt_mod
import re
from decimal import Decimal
from typing import Any

from flight_alert_scraper.models.query import CabinClass, Constraints, SearchQuery

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email(address: str) -> bool:
    return bool(_EMAIL_RE.match(address))


def row_from_form(form: Any, idx: int | None = None) -> dict[str, Any]:
    def _f(key: str) -> str:
        v = form.get(f"{key}_{idx}" if idx is not None else key)
        return str(v).strip() if v else ""

    max_price_raw = _f("max_price_usd")
    max_dur_raw = _f("max_duration_minutes")
    max_stops_raw = _f("max_stops")
    constraints_obj = Constraints(
        max_price_usd=(Decimal(max_price_raw) if max_price_raw else Decimal("9999")),
        max_duration_minutes=int(max_dur_raw) if max_dur_raw else None,
        max_stops=int(max_stops_raw) if max_stops_raw else None,
        value_deal_discount=Decimal(_f("value_deal_discount") or "0.20"),
        value_deal_duration_buffer_minutes=int(
            _f("value_deal_duration_buffer_minutes") or "180"
        ),
        time_saver_price_overage=Decimal(_f("time_saver_price_overage") or "0.10"),
        hourly_time_penalty_usd=Decimal(_f("hourly_time_penalty_usd") or "20.00"),
    )
    ret_raw = _f("return_date")
    query = SearchQuery(
        origin=_f("origin"),
        destination=_f("destination"),
        depart_date=dt_mod.date.fromisoformat(_f("depart_date")),
        return_date=(dt_mod.date.fromisoformat(ret_raw) if ret_raw else None),
        cabin=CabinClass(_f("cabin") or "economy"),
        adults=int(_f("adults") or "1"),
        constraints=constraints_obj,
    )
    row: dict[str, Any] = {
        "origin": query.origin,
        "destination": query.destination,
        "depart_date": query.depart_date.isoformat(),
        "cabin": str(query.cabin),
        "adults": query.adults,
        "constraints": {
            "max_price_usd": str(constraints_obj.max_price_usd),
            "max_duration_minutes": constraints_obj.max_duration_minutes,
            "max_stops": constraints_obj.max_stops,
            "value_deal_discount": str(constraints_obj.value_deal_discount),
            "value_deal_duration_buffer_minutes": (
                constraints_obj.value_deal_duration_buffer_minutes
            ),
            "time_saver_price_overage": str(constraints_obj.time_saver_price_overage),
            "hourly_time_penalty_usd": str(constraints_obj.hourly_time_penalty_usd),
        },
    }
    if ret_raw and query.return_date:
        row["return_date"] = query.return_date.isoformat()
    return row


def query_key_for_row(row: dict[str, Any]) -> str:
    c_data = row.get("constraints", {})
    constraints_obj = Constraints(**c_data)
    ret_raw = row.get("return_date")
    query = SearchQuery(
        origin=row["origin"],
        destination=row["destination"],
        depart_date=dt_mod.date.fromisoformat(row["depart_date"]),
        return_date=dt_mod.date.fromisoformat(ret_raw) if ret_raw else None,
        cabin=CabinClass(row.get("cabin", "economy")),
        adults=row.get("adults", 1),
        constraints=constraints_obj,
    )
    return query.query_key
