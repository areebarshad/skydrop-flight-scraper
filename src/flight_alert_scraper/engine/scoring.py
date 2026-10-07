from __future__ import annotations

from decimal import Decimal

from flight_alert_scraper.models.flight import FlightOption


def effective_cost(option: FlightOption, hourly_penalty: Decimal) -> Decimal:
    """Effective Cost = Price + (Duration in Hours * k)."""
    hours = Decimal(option.total_duration_minutes) / Decimal(60)
    return (option.price_usd + hours * hourly_penalty).quantize(Decimal("0.01"))


def pareto_front(options: list[FlightOption]) -> list[FlightOption]:
    """Keep only options not dominated on (price, duration). O(n^2)."""
    front = []
    for a in options:
        dominated = any(
            b.price_usd <= a.price_usd
            and b.total_duration_minutes <= a.total_duration_minutes
            and (
                b.price_usd < a.price_usd
                or b.total_duration_minutes < a.total_duration_minutes
            )
            for b in options
            if b.signature != a.signature
        )
        if not dominated:
            front.append(a)
    return front
