"""Optional SerpApi provider — only available when SERPAPI_KEY is set."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from flight_alert_scraper.models.flight import BookingLinks, FlightOption, Layover, Leg
from flight_alert_scraper.models.query import SearchQuery
from flight_alert_scraper.scrapers.base import ConfigError, ParseError, TransientError
from flight_alert_scraper.scrapers.links import build_links

log = logging.getLogger(__name__)

_BASE = "https://serpapi.com/search"


class SerpApiProvider:
    name = "serpapi"

    def __init__(self, api_key: str) -> None:
        self._key = api_key

    def available(self) -> bool:
        return bool(self._key)

    def search(self, query: SearchQuery) -> list[FlightOption]:
        if not self._key:
            raise ConfigError("SERPAPI_KEY is not set")

        params = {
            "engine": "google_flights",
            "departure_id": query.origin,
            "arrival_id": query.destination,
            "outbound_date": query.depart_date.isoformat(),
            "currency": "USD",
            "hl": "en",
            "api_key": self._key,
            "adults": str(query.adults),
        }
        if query.return_date:
            params["return_date"] = query.return_date.isoformat()

        log.info("serpapi searching %s->%s", query.origin, query.destination)
        try:
            resp = httpx.get(_BASE, params=params, timeout=30)
        except httpx.RequestError as exc:
            raise TransientError(f"SerpApi request failed: {exc}") from exc

        if resp.status_code == 401:
            raise ConfigError("Invalid SERPAPI_KEY")
        if resp.status_code >= 500:
            raise TransientError(f"SerpApi HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise ParseError(f"SerpApi HTTP {resp.status_code}")

        data = resp.json()
        flights_raw = data.get("best_flights", []) + data.get("other_flights", [])
        scraped_at = datetime.now(tz=timezone.utc)

        results: list[FlightOption] = []
        for item in flights_raw:
            try:
                results.append(_parse_item(item, query, scraped_at))
            except Exception as exc:
                log.warning("Skipping SerpApi item: %s", exc)

        if not results and flights_raw:
            raise ParseError("All SerpApi items failed to parse")

        return results


def _parse_item(item: dict, query: SearchQuery, scraped_at: datetime) -> FlightOption:
    price = Decimal(str(item["price"])).quantize(Decimal("0.01"))
    total_minutes = item.get("total_duration", 0)
    legs: list[Leg] = []
    layovers: list[Layover] = []

    for i, f in enumerate(item.get("flights", [])):
        dep_str = f.get("departure_airport", {}).get("time", "")
        arr_str = f.get("arrival_airport", {}).get("time", "")
        dep_at = datetime.fromisoformat(dep_str) if dep_str else scraped_at
        arr_at = datetime.fromisoformat(arr_str) if arr_str else scraped_at
        legs.append(
            Leg(
                carrier=f.get("airline", "Unknown"),
                carrier_code=f.get("airline_logo", "XX")[-6:-4].upper() or "XX",
                flight_number=f.get("flight_number", str(i)),
                origin=f["departure_airport"]["id"],
                destination=f["arrival_airport"]["id"],
                depart_at=dep_at,
                arrive_at=arr_at,
                duration_minutes=f.get("duration", 0),
                aircraft=f.get("airplane"),
            )
        )

    for lay in item.get("layovers", []):
        layovers.append(
            Layover(
                airport=lay["id"],
                duration_minutes=lay.get("duration", 0),
                overnight=lay.get("overnight", False),
            )
        )

    carrier_codes = [leg.carrier_code for leg in legs]
    links = build_links(query, carrier_codes=carrier_codes)
    return FlightOption(
        legs=legs,
        layovers=layovers,
        price_usd=price,
        total_duration_minutes=total_minutes,
        links=links,
        source="serpapi",
        scraped_at=scraped_at,
    )
