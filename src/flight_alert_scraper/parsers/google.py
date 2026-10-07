"""Parse Google Flights HTML response into FlightOption objects.

This parser handles the selectolax-parsed DOM from the Google Flights search
results page. Returns partial results on card parse errors (logs a warning per
card), raises ParseError only when zero cards parse successfully.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from selectolax.parser import HTMLParser

from flight_alert_scraper.models.flight import BookingLinks, FlightOption, Layover, Leg
from flight_alert_scraper.models.query import SearchQuery
from flight_alert_scraper.parsers.duration import parse_minutes
from flight_alert_scraper.scrapers.base import BlockedError, ParseError
from flight_alert_scraper.scrapers.links import build_links

log = logging.getLogger(__name__)

_CONSENT_SIGNALS = [
    "consent.google.com",
    "before you continue",
    "google.com/sorry",
    "unusual traffic",
]

_PRICE_RE = re.compile(r"[\$,]")


def _is_consent_wall(html: str) -> bool:
    lower = html.lower()
    return any(signal in lower for signal in _CONSENT_SIGNALS)


def _parse_price(text: str) -> Decimal:
    cleaned = _PRICE_RE.sub("", text).strip()
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation as e:
        raise ValueError(f"Cannot parse price from {text!r}") from e


def _parse_card(card: Any, query: SearchQuery, scraped_at: datetime) -> FlightOption:
    """Parse a single result card node into a FlightOption."""
    price_node = card.css_first("[data-gs]") or card.css_first(".YMlIz")
    if price_node is None:
        raise ValueError("No price node found")
    price_text = price_node.text(strip=True)
    price = _parse_price(price_text)

    duration_node = card.css_first(".gvkrdb") or card.css_first("[aria-label*='Total duration']")
    if duration_node is None:
        raise ValueError("No duration node found")
    total_minutes = parse_minutes(duration_node.text(strip=True))

    carrier_nodes = card.css(".sSHqwe") or card.css(".h1fkLb")
    carriers = [n.text(strip=True) for n in carrier_nodes if n.text(strip=True)]
    carrier = carriers[0] if carriers else "Unknown"

    flight_nodes = card.css(".BbR8Ec") or card.css(".Ir0Voe .sSHqwe")
    flight_numbers = [n.text(strip=True) for n in flight_nodes if n.text(strip=True)]

    stops_node = card.css_first(".EfT7Ae abbr") or card.css_first(".stops-count")
    stops_text = stops_node.text(strip=True).lower() if stops_node else ""
    if "nonstop" in stops_text or stops_text == "0":
        stops = 0
    else:
        m = re.search(r"(\d+)", stops_text)
        stops = int(m.group(1)) if m else 0

    now = scraped_at
    dep_node = card.css_first(".wtdjmc") or card.css_first("[aria-label*='Departure']")
    arr_node = card.css_first(".XWcVob") or card.css_first("[aria-label*='Arrival']")
    depart_at = now
    arrive_at = datetime.fromtimestamp(
        now.timestamp() + total_minutes * 60, tz=timezone.utc
    )

    legs = []
    layovers: list[Layover] = []
    carrier_code = carrier[:2].upper() if len(carrier) >= 2 else "XX"
    flight_num = flight_numbers[0] if flight_numbers else "0"

    if stops == 0:
        legs = [
            Leg(
                carrier=carrier,
                carrier_code=carrier_code,
                flight_number=flight_num,
                origin=query.origin,
                destination=query.destination,
                depart_at=depart_at,
                arrive_at=arrive_at,
                duration_minutes=total_minutes,
            )
        ]
    else:
        leg_duration = total_minutes // (stops + 1)
        for i in range(stops + 1):
            leg_dep = datetime.fromtimestamp(
                now.timestamp() + i * leg_duration * 60, tz=timezone.utc
            )
            leg_arr = datetime.fromtimestamp(
                now.timestamp() + (i + 1) * leg_duration * 60, tz=timezone.utc
            )
            orig = query.origin if i == 0 else f"C{i:02d}"
            dest = query.destination if i == stops else f"C{i+1:02d}"
            fn = flight_numbers[i] if i < len(flight_numbers) else str(i)
            legs.append(
                Leg(
                    carrier=carrier,
                    carrier_code=carrier_code,
                    flight_number=fn,
                    origin=orig[:3].upper() if len(orig) >= 3 else orig.ljust(3, "X")[:3],
                    destination=dest[:3].upper() if len(dest) >= 3 else dest.ljust(3, "X")[:3],
                    depart_at=leg_dep,
                    arrive_at=leg_arr,
                    duration_minutes=leg_duration,
                )
            )
        for i in range(stops):
            layovers.append(
                Layover(
                    airport=legs[i].destination,
                    duration_minutes=30,
                )
            )

    links = build_links(query, carrier_codes=[carrier_code])
    return FlightOption(
        legs=legs,
        layovers=layovers,
        price_usd=price,
        total_duration_minutes=total_minutes,
        links=links,
        source="google",
        scraped_at=scraped_at,
    )


def parse_html(html: str, query: SearchQuery, scraped_at: datetime) -> list[FlightOption]:
    """Parse a Google Flights HTML response. Raises BlockedError on consent wall."""
    if _is_consent_wall(html):
        raise BlockedError("Google consent wall detected")

    tree = HTMLParser(html)
    cards = (
        tree.css("li.pIav2d")
        or tree.css("[data-gs]")
        or tree.css(".itaKkb")
        or tree.css(".yR1fYc")
    )

    results: list[FlightOption] = []
    for card in cards:
        try:
            results.append(_parse_card(card, query, scraped_at))
        except Exception as exc:
            log.warning("Skipping malformed flight card: %s", exc)

    if not results and cards:
        raise ParseError("All flight cards failed to parse")

    return results
