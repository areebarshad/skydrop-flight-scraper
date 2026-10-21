from __future__ import annotations

import json
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
        "stops": snap.stops,
        "carriers": snap.carriers,
        "tier": snap.tier,
        "labels": labels,
        "effective_cost": fmt_price(snap.effective_cost_usd),
        "booking_link": booking_link,
    }


def build_price_svg(history: list[PriceHistoryPoint], budget: Decimal) -> str | None:
    if not history:
        return None
    W, H = 600, 130
    PT, PR, PB, PL = 10, 15, 30, 55
    chart_w = W - PL - PR
    chart_h = H - PT - PB

    all_prices: list[float] = [float(budget)]
    for h in history:
        if h["min_tier1_price"] is not None:
            all_prices.append(float(h["min_tier1_price"]))
        all_prices.append(float(h["min_overall_price"]))
    min_p = min(all_prices) * 0.95
    max_p = max(all_prices) * 1.05
    p_range = max_p - min_p or 1.0
    n = len(history)

    def px(i: int) -> float:
        if n == 1:
            return PL + chart_w / 2.0
        return PL + (i / (n - 1)) * chart_w

    def py(price: float) -> float:
        return PT + chart_h - (price - min_p) / p_range * chart_h

    budget_y = py(float(budget))
    first_label = history[0]["observed_at"].strftime("%b %d")
    last_label = history[-1]["observed_at"].strftime("%b %d")

    ns = 'xmlns="http://www.w3.org/2000/svg"'
    parts = [
        f'<svg viewBox="0 0 {W} {H}" {ns} class="price-chart" aria-hidden="true">'
    ]
    overall_stroke = 'stroke="var(--c-line-overall)" stroke-width="1.5" opacity="0.5"'
    if n == 1:
        ox = px(0)
        oy = py(float(history[0]["min_overall_price"]))
        parts.append(
            f'  <circle cx="{ox:.1f}" cy="{oy:.1f}" r="3.5"'
            ' fill="var(--c-line-overall)" opacity="0.5"/>'
        )
    else:
        overall_pts = " ".join(
            f"{px(i):.1f},{py(float(h['min_overall_price'])):.1f}"
            for i, h in enumerate(history)
        )
        parts.append(
            f'  <polyline points="{overall_pts}" fill="none" {overall_stroke}/>'
        )

    tier1_segs: list[list[str]] = []
    seg: list[str] = []
    for i, h in enumerate(history):
        if h["min_tier1_price"] is not None:
            seg.append(f"{px(i):.1f},{py(float(h['min_tier1_price'])):.1f}")
        else:
            if seg:
                tier1_segs.append(seg)
                seg = []
    if seg:
        tier1_segs.append(seg)

    t1_stroke = 'stroke="var(--c-line-tier1)" stroke-width="2.5"'
    for s in tier1_segs:
        if len(s) >= 2:
            pts_str = " ".join(s)
            parts.append(
                f'  <polyline points="{pts_str}" fill="none" {t1_stroke}/>'
            )
        elif len(s) == 1:
            x, y = s[0].split(",")
            parts.append(
                f'  <circle cx="{x}" cy="{y}" r="3.5" fill="var(--c-line-tier1)"/>'
            )
    parts.append(
        f'  <line x1="{PL}" y1="{budget_y:.1f}" x2="{W - PR}" y2="{budget_y:.1f}"'
        f' stroke="var(--c-budget-line)" stroke-width="1.5" stroke-dasharray="5 3"/>'
    )
    for label, yval in [
        (f"${int(min_p)}", py(min_p)),
        (f"${int(float(budget))}", budget_y),
        (f"${int(max_p)}", py(max_p)),
    ]:
        parts.append(
            f'  <text x="{PL - 4}" y="{yval:.1f}" text-anchor="end"'
            f' dominant-baseline="middle" class="chart-label">{label}</text>'
        )
    parts.append(
        f'  <text x="{PL}" y="{H - 5}" text-anchor="start"'
        f' class="chart-label">{first_label}</text>'
    )
    parts.append(
        f'  <text x="{W - PR}" y="{H - 5}" text-anchor="end"'
        f' class="chart-label">{last_label}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)
