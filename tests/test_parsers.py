"""Tests for duration parser."""
from __future__ import annotations

import pytest

from flight_alert_scraper.parsers.duration import parse_minutes


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
