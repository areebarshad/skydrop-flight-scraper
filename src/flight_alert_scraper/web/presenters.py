from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from flight_alert_scraper.db.repo import PriceHistoryPoint
from flight_alert_scraper.db.tables import FlightSnapshot


_PROVIDER_LABELS: dict[str, str] = {
    "google_http": "web",
    "google_browser": "browser",
    "serpapi": "serp",
}


def fmt_provider(provider: str | None) -> str:
    if provider is None:
        return "unknown"
    return _PROVIDER_LABELS.get(provider, provider)


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


def compute_chart_stats(
    history: list[PriceHistoryPoint],
    budget: Decimal,
    mode: str = "overall",
) -> dict[str, Any] | None:
    """Return mean/std/current/hist_best stats for displaying below the chart."""
    if not history:
        return None
    raw_overall = [float(h["min_overall_price"]) for h in history]
    raw_tier1 = [float(h["min_tier1_price"]) for h in history if h["min_tier1_price"] is not None]
    prices = raw_tier1 if mode == "tier1" and raw_tier1 else raw_overall
    if not prices:
        return None
    n = len(prices)
    mean = sum(prices) / n
    variance = sum((p - mean) ** 2 for p in prices) / (n - 1) if n > 1 else 0
    std = math.sqrt(variance) if variance > 0 else mean * 0.06
    current = prices[-1]   # most recent run — reflects currently bookable fares
    hist_min = min(prices)  # all-time low across all runs
    return {
        "mean": fmt_price(Decimal(str(round(mean))).quantize(Decimal("1"))),
        "std": fmt_price(Decimal(str(round(std))).quantize(Decimal("1"))),
        "best": fmt_price(Decimal(str(round(current))).quantize(Decimal("1"))),
        "hist_best": fmt_price(Decimal(str(round(hist_min))).quantize(Decimal("1"))),
        "hist_best_differs": hist_min < current * 0.999,
        "n": n,
    }


def build_price_distribution_svg(
    history: list[PriceHistoryPoint],
    budget: Decimal,
    mode: str = "overall",
) -> str | None:
    """Minimal bell-curve distribution chart — white background, thin crisp curve."""
    if not history:
        return None

    raw_overall = [float(h["min_overall_price"]) for h in history]
    raw_tier1 = [float(h["min_tier1_price"]) for h in history if h["min_tier1_price"] is not None]

    prices = raw_tier1 if mode == "tier1" and raw_tier1 else raw_overall
    if not prices:
        return None

    n = len(prices)
    mean = sum(prices) / n
    variance = sum((p - mean) ** 2 for p in prices) / (n - 1) if n > 1 else 0
    std = math.sqrt(variance) if variance > 0 else mean * 0.06
    min_price = prices[-1]   # current run — the fare you can actually book now
    hist_best = min(prices)  # all-time low shown separately if lower

    # Symmetric range centred on the mean so the bell curve sits in the middle
    half = max(
        abs(min_price - mean),
        abs(hist_best - mean),
        abs(max(prices) - mean),
        3.0 * std,
    ) * 1.10
    x_lo = mean - half
    x_hi = mean + half
    x_range = x_hi - x_lo or 1.0

    W, H = 640, 170
    PT, PR, PB, PL = 20, 24, 24, 32
    cw = W - PL - PR
    ch = H - PT - PB
    baseline_y = PT + ch

    def sx(v: float) -> float:
        return PL + (v - x_lo) / x_range * cw

    def curve_y(xv: float) -> float:
        max_pdf = 1.0 / (std * math.sqrt(2 * math.pi))
        z = (xv - mean) / std
        pdf = math.exp(-0.5 * z * z) / (std * math.sqrt(2 * math.pi))
        return PT + ch - (pdf / max_pdf) * ch * 0.84

    n_steps = 320
    curve_pts: list[str] = []
    for i in range(n_steps + 1):
        xv = x_lo + x_range * i / n_steps
        curve_pts.append(f"{sx(xv):.1f},{curve_y(xv):.1f}")

    fill_pts = curve_pts + [f"{sx(x_hi):.1f},{baseline_y}", f"{sx(x_lo):.1f},{baseline_y}"]

    ns = 'xmlns="http://www.w3.org/2000/svg"'
    grad_id = f"cg{mode}"
    data_attrs = (
        f'data-xlo="{x_lo:.2f}" data-xhi="{x_hi:.2f}" '
        f'data-pl="{PL}" data-pt="{PT}" data-cw="{cw:.2f}" data-ch="{ch:.2f}" '
        f'data-baseline="{baseline_y}" data-mean="{mean:.2f}" data-std="{std:.2f}" '
        f'data-w="{W}" data-h="{H}"'
    )

    parts = [f'<svg viewBox="0 0 {W} {H}" {ns} class="price-chart dist-chart" '
             f'style="cursor:crosshair;overflow:visible" {data_attrs}>']

    # White background
    parts.append(f'  <rect x="0" y="0" width="{W}" height="{H}" fill="white" rx="4"/>')

    # Defs: gradient only (no glow filter)
    parts.append(f'''  <defs>
    <linearGradient id="{grad_id}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="rgba(0,102,255,0.10)"/>
      <stop offset="80%" stop-color="rgba(0,102,255,0.02)"/>
      <stop offset="100%" stop-color="rgba(0,102,255,0)"/>
    </linearGradient>
  </defs>''')

    # ±1 std band — very subtle
    x1s = sx(mean - std)
    x2s = sx(mean + std)
    parts.append(
        f'  <rect x="{x1s:.1f}" y="{PT}" width="{x2s - x1s:.1f}" height="{ch}" '
        f'fill="rgba(0,102,255,0.04)" stroke="rgba(0,102,255,0.08)" '
        f'stroke-width="0.5" rx="2"/>'
    )

    # Fill under curve
    parts.append(
        f'  <polygon points="{" ".join(fill_pts)}" fill="url(#{grad_id})" stroke="none"/>'
    )

    # Thin, crisp curve — no glow, no blur
    parts.append(
        f'  <polyline points="{" ".join(curve_pts)}" fill="none" '
        f'stroke="#0066FF" stroke-width="1.5" stroke-linejoin="round" opacity="0.80"/>'
    )

    # Baseline
    parts.append(
        f'  <line x1="{PL}" y1="{baseline_y}" x2="{W - PR}" y2="{baseline_y}" '
        f'stroke="rgba(0,0,0,0.08)" stroke-width="1"/>'
    )

    # Data ticks
    for p in prices:
        xi = sx(p)
        is_current = p == min_price
        col = "rgba(5,150,105,0.80)" if is_current else "rgba(100,116,139,0.20)"
        th = 8 if is_current else 4
        parts.append(
            f'  <line x1="{xi:.1f}" y1="{baseline_y - th}" x2="{xi:.1f}" y2="{baseline_y}" '
            f'stroke="{col}" stroke-width="{2 if is_current else 1}" stroke-linecap="round"/>'
        )

    # Current price marker (green)
    xi_cheap = sx(min_price)
    cy_best = curve_y(min_price)
    parts.append(
        f'  <line x1="{xi_cheap:.1f}" y1="{cy_best:.1f}" x2="{xi_cheap:.1f}" y2="{baseline_y - 10}" '
        f'stroke="rgba(5,150,105,0.35)" stroke-width="1"/>'
    )
    parts.append(
        f'  <circle cx="{xi_cheap:.1f}" cy="{cy_best:.1f}" r="4.5" '
        f'fill="#059669" stroke="white" stroke-width="1.5"/>'
    )

    # Historical best marker (grey) — only if meaningfully lower than current
    if hist_best < min_price * 0.999:
        xi_hb = sx(hist_best)
        cy_hb = curve_y(hist_best)
        parts.append(
            f'  <line x1="{xi_hb:.1f}" y1="{cy_hb:.1f}" x2="{xi_hb:.1f}" y2="{baseline_y - 6}" '
            f'stroke="rgba(100,116,139,0.30)" stroke-width="1"/>'
        )
        parts.append(
            f'  <circle cx="{xi_hb:.1f}" cy="{cy_hb:.1f}" r="3.5" '
            f'fill="#94A3B8" stroke="white" stroke-width="1.5"/>'
        )

    # Mean line — solid, thin, subtle
    xi_mean = sx(mean)
    parts.append(
        f'  <line x1="{xi_mean:.1f}" y1="{PT}" x2="{xi_mean:.1f}" y2="{baseline_y}" '
        f'stroke="rgba(0,102,255,0.22)" stroke-width="1"/>'
    )

    # Interactive cursor group (JS will move/show these)
    parts.append(f'  <g id="dist-cursor" visibility="hidden" pointer-events="none">')
    parts.append(
        f'    <line id="dist-cursor-vline" x1="0" y1="{PT}" x2="0" y2="{baseline_y}" '
        f'stroke="rgba(0,0,0,0.18)" stroke-width="1"/>'
    )
    parts.append(
        f'    <circle id="dist-cursor-dot" cx="0" cy="{PT}" r="4" '
        f'fill="#0066FF" stroke="white" stroke-width="1.5"/>'
    )
    parts.append('  </g>')

    # Transparent hit area — on top so it captures mouse events
    parts.append(
        f'  <rect class="dist-hit" x="{PL}" y="{PT}" width="{cw:.1f}" height="{ch}" '
        f'fill="transparent"/>'
    )

    parts.append("</svg>")
    return "\n".join(parts)


def build_price_svg(history: list[PriceHistoryPoint], budget: Decimal) -> str | None:
    """Legacy alias — delegates to distribution chart."""
    return build_price_distribution_svg(history, budget, mode="overall")
