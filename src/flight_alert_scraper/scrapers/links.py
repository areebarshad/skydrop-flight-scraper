"""Build resilient booking links from a search query."""
from __future__ import annotations

from flight_alert_scraper.models.flight import BookingLinks
from flight_alert_scraper.models.query import SearchQuery
from flight_alert_scraper.scrapers.tfs import encode as encode_tfs

_CARRIER_URL_TEMPLATES: dict[str, str] = {
    "PK": "https://www.piac.com.pk/",
    "EK": "https://www.emirates.com/",
    "QR": "https://www.qatarairways.com/",
    "TK": "https://www.turkishairlines.com/",
    "EY": "https://www.etihad.com/",
}


def build_links(query: SearchQuery, carrier_codes: list[str] | None = None) -> BookingLinks:
    tfs = encode_tfs(query)
    google = f"https://www.google.com/travel/flights/search?tfs={tfs}&curr=USD&gl=us"

    dep = query.depart_date.strftime("%Y-%m-%d")
    kayak = f"https://www.kayak.com/flights/{query.origin}-{query.destination}/{dep}"
    if query.return_date:
        ret = query.return_date.strftime("%Y-%m-%d")
        kayak += f"/{ret}"

    airline_direct: str | None = None
    if carrier_codes:
        for code in carrier_codes:
            if code in _CARRIER_URL_TEMPLATES:
                airline_direct = _CARRIER_URL_TEMPLATES[code]
                break

    return BookingLinks(
        google_search=google,
        kayak_search=kayak,
        airline_direct=airline_direct,
    )
