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


def compute_chart_stats(
    history: list[PriceHistoryPoint],
    budget: Decimal,
    mode: str = "overall",
) -> dict[str, Any] | None:
    """Return mean/std/best stats for displaying below the chart."""
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
    return {
        "mean": fmt_price(Decimal(str(round(mean))).quantize(Decimal("1"))),
        "std": fmt_price(Decimal(str(round(std))).quantize(Decimal("1"))),
        "best": fmt_price(Decimal(str(round(min(prices)))).quantize(Decimal("1"))),
        "n": n,
    }


def build_price_distribution_svg(
    history: list[PriceHistoryPoint],
    budget: Decimal,
    mode: str = "overall",
) -> str | None:
    """Modern glassy bell-curve distribution chart."""
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
    budget_val = float(budget)
    min_price = min(prices)

    x_lo = min(min_price, mean - 2.8 * std, budget_val) * 0.96
    x_hi = max(max(prices), mean + 2.8 * std, budget_val) * 1.04
    x_range = x_hi - x_lo or 1.0

    W, H = 640, 190
    PT, PR, PB, PL = 28, 28, 46, 36
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
    glow_id = f"gw{mode}"
    data_attrs = (
        f'data-xlo="{x_lo:.2f}" data-xhi="{x_hi:.2f}" '
        f'data-pl="{PL}" data-pt="{PT}" data-cw="{cw:.2f}" data-ch="{ch:.2f}" '
        f'data-baseline="{baseline_y}" data-mean="{mean:.2f}" data-std="{std:.2f}" '
        f'data-w="{W}" data-h="{H}"'
    )

    parts = [f'<svg viewBox="0 0 {W} {H}" {ns} class="price-chart dist-chart" '
             f'style="cursor:crosshair;overflow:visible" {data_attrs}>']

    # Defs: gradient + glow filter
    parts.append(f'''  <defs>
    <linearGradient id="{grad_id}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="rgba(0,120,255,0.38)"/>
      <stop offset="75%" stop-color="rgba(0,80,200,0.12)"/>
      <stop offset="100%" stop-color="rgba(0,60,180,0.02)"/>
    </linearGradient>
    <filter id="{glow_id}" x="-10%" y="-30%" width="120%" height="160%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>''')

    # ±1 std band — subtle
    x1s = sx(mean - std)
    x2s = sx(mean + std)
    parts.append(
        f'  <rect x="{x1s:.1f}" y="{PT}" width="{x2s - x1s:.1f}" height="{ch}" '
        f'fill="rgba(0,100,255,0.04)" stroke="rgba(0,100,255,0.12)" '
        f'stroke-width="0.5" stroke-dasharray="2 3" rx="2"/>'
    )

    # Fill under curve
    parts.append(
        f'  <polygon points="{" ".join(fill_pts)}" fill="url(#{grad_id})" stroke="none"/>'
    )

    # Glow layer of curve
    parts.append(
        f'  <polyline points="{" ".join(curve_pts)}" fill="none" '
        f'stroke="rgba(0,140,255,0.45)" stroke-width="4" stroke-linejoin="round" '
        f'filter="url(#{glow_id})"/>'
    )
    # Crisp curve on top
    parts.append(
        f'  <polyline points="{" ".join(curve_pts)}" fill="none" '
        f'stroke="rgba(30,160,255,0.92)" stroke-width="1.8" stroke-linejoin="round"/>'
    )

    # Baseline
    parts.append(
        f'  <line x1="{PL}" y1="{baseline_y}" x2="{W - PR}" y2="{baseline_y}" '
        f'stroke="rgba(148,163,184,0.25)" stroke-width="1"/>'
    )

    # Budget line
    if x_lo < budget_val < x_hi:
        xi_b = sx(budget_val)
        parts.append(
            f'  <line x1="{xi_b:.1f}" y1="{PT + 4}" x2="{xi_b:.1f}" y2="{baseline_y}" '
            f'stroke="rgba(244,63,94,0.55)" stroke-width="1.5" stroke-dasharray="5 3"/>'
        )
        bx_anchor = "middle"
        if xi_b < PL + 50:
            bx_anchor = "start"
        elif xi_b > W - PR - 50:
            bx_anchor = "end"
        parts.append(
            f'  <text x="{xi_b:.1f}" y="{H - 4}" text-anchor="{bx_anchor}" '
            f'class="chart-label" fill="rgba(244,63,94,0.65)">budget ${int(budget_val):,}</text>'
        )

    # Data ticks
    for p in prices:
        xi = sx(p)
        is_best = p == min_price
        col = "rgba(16,185,129,0.85)" if is_best else "rgba(100,116,139,0.35)"
        th = 8 if is_best else 4
        parts.append(
            f'  <line x1="{xi:.1f}" y1="{baseline_y - th}" x2="{xi:.1f}" y2="{baseline_y + 2}" '
            f'stroke="{col}" stroke-width="{2 if is_best else 1}" stroke-linecap="round"/>'
        )

    # Best marker
    xi_cheap = sx(min_price)
    cy_best = curve_y(min_price)
    parts.append(
        f'  <line x1="{xi_cheap:.1f}" y1="{cy_best:.1f}" x2="{xi_cheap:.1f}" y2="{baseline_y - 10}" '
        f'stroke="rgba(16,185,129,0.5)" stroke-width="1" stroke-dasharray="3 2"/>'
    )
    parts.append(
        f'  <circle cx="{xi_cheap:.1f}" cy="{cy_best:.1f}" r="5" '
        f'fill="rgba(16,185,129,0.9)" stroke="rgba(255,255,255,0.85)" stroke-width="1.5"/>'
    )

    # Mean dashed line
    xi_mean = sx(mean)
    parts.append(
        f'  <line x1="{xi_mean:.1f}" y1="{PT + 2}" x2="{xi_mean:.1f}" y2="{baseline_y}" '
        f'stroke="rgba(148,163,184,0.35)" stroke-width="1" stroke-dasharray="4 3"/>'
    )

    # X-axis labels
    def _lbl(txt: str, lx: float, color: str = "rgba(100,116,139,0.7)") -> None:
        anchor = "middle"
        if lx < PL + 44:
            anchor = "start"
        elif lx > W - PR - 44:
            anchor = "end"
        parts.append(
            f'  <text x="{lx:.1f}" y="{H - 4}" text-anchor="{anchor}" '
            f'class="chart-label" fill="{color}">{txt}</text>'
        )

    _lbl(f"best ${int(min_price):,}", xi_cheap, "rgba(16,185,129,0.8)")
    _lbl(f"avg ${int(mean):,}", xi_mean)

    # Interactive cursor group (JS will move/show these)
    parts.append(f'  <g id="dist-cursor" visibility="hidden" pointer-events="none">')
    parts.append(
        f'    <line id="dist-cursor-vline" x1="0" y1="{PT}" x2="0" y2="{baseline_y}" '
        f'stroke="rgba(255,255,255,0.55)" stroke-width="1" stroke-dasharray="3 2"/>'
    )
    parts.append(
        f'    <circle id="dist-cursor-dot" cx="0" cy="{PT}" r="4.5" '
        f'fill="rgba(0,140,255,0.9)" stroke="rgba(255,255,255,0.85)" stroke-width="1.5"/>'
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
