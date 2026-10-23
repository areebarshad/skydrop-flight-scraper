from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from flight_alert_scraper.db.repo import PriceHistoryPoint
from flight_alert_scraper.db.tables import FlightSnapshot


def fmt_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m" if m else f"{h}h"


def fmt_price(price: Decimal) -> str:
    return f"${price:,.0f}"


def fmt_relative_time(dt: datetime | None) -> str:
    if dt is None:
        return "never"
    now = datetime.now(tz=UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _full_carrier_names(option_json: str, fallback: str) -> str:
    try:
        opt = json.loads(option_json)
        seen: list[str] = []
        for leg in opt.get("legs", []):
            name = leg.get("carrier") or leg.get("carrier_code", "")
            if name and name not in seen:
                seen.append(name)
        return " · ".join(seen) if seen else fallback
    except Exception:
        return fallback


def snapshot_to_card(snap: FlightSnapshot) -> dict[str, Any]:
    labels: list[str] = json.loads(snap.labels)
    booking_link = "#"
    try:
        opt = json.loads(snap.option_json)
        booking_link = opt.get("links", {}).get("google_search", "#")
    except Exception:
        pass
    return {
        "signature": snap.signature,
        "price": fmt_price(snap.price_usd),
        "price_raw": float(snap.price_usd),
        "duration": fmt_duration(snap.total_duration_minutes),
        "duration_raw": snap.total_duration_minutes,
        "stops": snap.stops,
        "carriers": _full_carrier_names(snap.option_json, snap.carriers),
        "tier": snap.tier,
        "labels": labels,
        "effective_cost": fmt_price(snap.effective_cost_usd),
        "effective_raw": float(snap.effective_cost_usd),
        "booking_link": booking_link,
    }


def build_price_distribution_svg(
    history: list[PriceHistoryPoint],
    budget: Decimal,
    mode: str = "overall",
) -> str | None:
    """Normal distribution (bell curve) of historical prices."""
    if not history:
        return None

    raw_overall = [float(h["min_overall_price"]) for h in history]
    raw_tier1 = [float(h["min_tier1_price"]) for h in history if h["min_tier1_price"] is not None]

    prices = raw_tier1 if mode == "tier1" and raw_tier1 else raw_overall
    if not prices:
        return None

    n = len(prices)
    mean = sum(prices) / n
    variance = sum((p - mean) ** 2 for p in prices) / n
    std = math.sqrt(variance) if variance > 1 else mean * 0.05
    budget_val = float(budget)
    min_price = min(prices)

    # X range covers all data + 2.5 std each side + budget
    x_lo = min(min_price, mean - 2.5 * std, budget_val) * 0.97
    x_hi = max(max(prices), mean + 2.5 * std, budget_val) * 1.03
    x_range = x_hi - x_lo or 1.0

    W, H = 600, 170
    PT, PR, PB, PL = 16, 20, 48, 20
    cw = W - PL - PR
    ch = H - PT - PB
    baseline_y = PT + ch

    def sx(v: float) -> float:
        return PL + (v - x_lo) / x_range * cw

    max_pdf = 1.0 / (std * math.sqrt(2 * math.pi))

    # Bell curve polyline (200 steps)
    n_steps = 200
    curve_pts: list[str] = []
    for i in range(n_steps + 1):
        xv = x_lo + x_range * i / n_steps
        z = (xv - mean) / std
        pdf = math.exp(-0.5 * z * z) / (std * math.sqrt(2 * math.pi))
        yv = PT + ch - (pdf / max_pdf) * ch * 0.82
        curve_pts.append(f"{sx(xv):.1f},{yv:.1f}")

    # Filled area polygon (close bottom of curve)
    fill_pts = (
        curve_pts
        + [f"{sx(x_hi):.1f},{baseline_y}", f"{sx(x_lo):.1f},{baseline_y}"]
    )

    ns = 'xmlns="http://www.w3.org/2000/svg"'
    parts = [f'<svg viewBox="0 0 {W} {H}" {ns} class="price-chart dist-chart" aria-hidden="true">']

    # ±1 std band
    x1s = sx(mean - std)
    x2s = sx(mean + std)
    parts.append(
        f'  <rect x="{x1s:.1f}" y="{PT}" width="{x2s - x1s:.1f}" height="{ch}"'
        f' fill="rgba(0,102,255,0.04)" stroke="none"/>'
    )

    # Fill under curve
    parts.append(
        f'  <polygon points="{" ".join(fill_pts)}" fill="rgba(0,102,255,0.07)" stroke="none"/>'
    )

    # Curve line
    parts.append(
        f'  <polyline points="{" ".join(curve_pts)}" fill="none"'
        f' stroke="var(--c-line-overall)" stroke-width="2" stroke-linejoin="round"/>'
    )

    # Baseline axis
    parts.append(
        f'  <line x1="{PL}" y1="{baseline_y}" x2="{W - PR}" y2="{baseline_y}"'
        f' stroke="rgba(148,163,184,0.4)" stroke-width="1"/>'
    )

    # Data point ticks on baseline
    for p in prices:
        xi = sx(p)
        is_cheapest = p == min_price
        color = "var(--tier1)" if is_cheapest else "var(--c-line-overall)"
        tick_h = 8 if is_cheapest else 5
        parts.append(
            f'  <line x1="{xi:.1f}" y1="{baseline_y - tick_h}" x2="{xi:.1f}" y2="{baseline_y + 3}"'
            f' stroke="{color}" stroke-width="{2 if is_cheapest else 1.5}" stroke-linecap="round"/>'
        )

    # Cheapest dot above baseline
    xi_cheap = sx(min_price)
    parts.append(
        f'  <circle cx="{xi_cheap:.1f}" cy="{baseline_y - 16}" r="5"'
        f' fill="var(--tier1)" stroke="white" stroke-width="2"/>'
    )
    parts.append(
        f'  <text x="{xi_cheap:.1f}" y="{baseline_y - 26}" text-anchor="middle"'
        f' class="chart-label dist-label-deal">best</text>'
    )

    # Mean vertical dashed
    xi_mean = sx(mean)
    parts.append(
        f'  <line x1="{xi_mean:.1f}" y1="{PT}" x2="{xi_mean:.1f}" y2="{baseline_y}"'
        f' stroke="var(--c-line-overall)" stroke-width="1.2" stroke-dasharray="4 3" opacity="0.55"/>'
    )
    parts.append(
        f'  <text x="{xi_mean:.1f}" y="{PT + 9}" text-anchor="middle" class="chart-label">avg</text>'
    )

    # Budget vertical dashed (only if within range)
    if x_lo < budget_val < x_hi:
        xi_budget = sx(budget_val)
        parts.append(
            f'  <line x1="{xi_budget:.1f}" y1="{PT}" x2="{xi_budget:.1f}" y2="{baseline_y}"'
            f' stroke="var(--c-budget-line)" stroke-width="1.5" stroke-dasharray="5 3"/>'
        )

    # X-axis price labels — cheapest, mean, budget
    label_xs: list[tuple[str, float]] = [
        (f"${int(min_price):,}", xi_cheap),
        (f"avg ${int(mean):,}", xi_mean),
    ]
    if x_lo < budget_val < x_hi:
        label_xs.append((f"budget ${int(budget_val):,}", sx(budget_val)))

    for txt, lx in label_xs:
        anchor = "middle"
        if lx < PL + 40:
            anchor = "start"
        elif lx > W - PR - 40:
            anchor = "end"
        parts.append(
            f'  <text x="{lx:.1f}" y="{H - 6}" text-anchor="{anchor}" class="chart-label">{txt}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def build_price_svg(history: list[PriceHistoryPoint], budget: Decimal) -> str | None:
    """Legacy alias — delegates to distribution chart."""
    return build_price_distribution_svg(history, budget, mode="overall")
