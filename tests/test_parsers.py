"""Tests for duration parser and Google Flights page classifier."""
from __future__ import annotations

import gzip
import unittest.mock as mock
from pathlib import Path

import pytest

from flight_alert_scraper.parsers.duration import parse_minutes
from flight_alert_scraper.parsers.google import classify_page
from flight_alert_scraper.scrapers.base import RenderTimeoutError

_FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> str:
    return gzip.decompress((_FIXTURES / name).read_bytes()).decode()


# ── duration parser ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("22h 30m", 1350),
    ("22h", 1320),
    ("45 min", 45),
    ("1 day 10 hr 15 min", 2055),
    ("1 day 10 hours 15 minutes", 2055),
    ("34 minutes", 34),
    ("2h", 120),
    ("1h 0m", 60),
    ("0h 30m", 30),
])
def test_parse_minutes(text: str, expected: int) -> None:
    assert parse_minutes(text) == expected


def test_parse_minutes_invalid() -> None:
    with pytest.raises(ValueError):
        parse_minutes("not a duration")


def test_parse_minutes_zero_raises() -> None:
    with pytest.raises(ValueError):
        parse_minutes("0h 0m")


# ── classify_page — real captures ─────────────────────────────────────────────

def test_classify_ruh_khi_results() -> None:
    html = _load_fixture("google_ruh_khi_results.html.gz")
    assert classify_page(html) == "results"


def test_classify_iad_khi_not_rendered() -> None:
    html = _load_fixture("google_iad_khi_not_rendered.html.gz")
    assert classify_page(html) == "not_rendered"



# ── GoogleHttpProvider raises on not_rendered ──────────────────────────────────

def test_google_http_raises_render_timeout_on_not_rendered() -> None:
    from flight_alert_scraper.scrapers.google_http import GoogleHttpProvider
    from tests.conftest import make_query

    html = _load_fixture("google_iad_khi_not_rendered.html.gz")
    provider = GoogleHttpProvider()
    query = make_query()

    with mock.patch.object(provider, "_fetch", return_value=html), \
         mock.patch("flight_alert_scraper.scrapers.google_http._save_artifact"):
        with pytest.raises(RenderTimeoutError):
            provider.search(query)
