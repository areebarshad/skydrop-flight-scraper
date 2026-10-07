"""Parse human-readable duration strings into integer minutes."""
from __future__ import annotations

import re

_PATTERN = re.compile(
    r"(?:(\d+)\s*d(?:ay)?s?)?\s*"
    r"(?:(\d+)\s*h(?:r|our)?s?)?\s*"
    r"(?:(\d+)\s*m(?:in(?:ute)?s?)?)?",
    re.IGNORECASE,
)


def parse_minutes(text: str) -> int:
    """Convert strings like '1 day 10 hr 15 min', '22h 30m', '45 min' to minutes."""
    m = _PATTERN.match(text.strip())
    if not m or not any(m.groups()):
        raise ValueError(f"Cannot parse duration: {text!r}")
    days = int(m.group(1) or 0)
    hours = int(m.group(2) or 0)
    minutes = int(m.group(3) or 0)
    total = days * 1440 + hours * 60 + minutes
    if total == 0:
        raise ValueError(f"Duration parsed as zero from: {text!r}")
    return total
