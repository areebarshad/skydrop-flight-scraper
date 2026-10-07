"""Render email templates for immediate and digest alerts."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from flight_alert_scraper.models.alert import AlertDecision, AlertKind

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def render_html(decision: AlertDecision) -> str:
    env = _env()
    if decision.kind == AlertKind.IMMEDIATE:
        tmpl = env.get_template("immediate.html.j2")
    else:
        tmpl = env.get_template("digest.html.j2")
    return tmpl.render(ranked=decision.ranked, decision=decision)


def render_text(decision: AlertDecision) -> str:
    env = _env()
    if decision.kind == AlertKind.IMMEDIATE:
        tmpl = env.get_template("immediate.txt.j2")
    else:
        tmpl = env.get_template("digest.txt.j2")
    return tmpl.render(ranked=decision.ranked, decision=decision)


def render_subject(decision: AlertDecision) -> str:
    q = decision.ranked.query
    route = f"{q.origin}→{q.destination}"
    if decision.kind == AlertKind.IMMEDIATE and decision.ranked.tier1:
        best = decision.ranked.tier1[0]
        h, m = divmod(best.option.total_duration_minutes, 60)
        dur = f"{h}h {m}m" if m else f"{h}h"
        return f"[Tier 1] {route} ${best.option.price_usd:.0f} / {dur} — new match"
    elif decision.kind == AlertKind.IMMEDIATE and decision.ranked.tier2:
        best = decision.ranked.tier2[0]
        return f"[Tier 1] {route} — price update ${best.option.price_usd:.0f}"
    else:
        c = q.constraints
        limit_str = f"{c.max_duration_minutes // 60}h" if c.max_duration_minutes else "no limit"
        return (
            f"[Digest] {route} — no match under {limit_str}/${c.max_price_usd:.0f}; "
            + (
                f"best alt ${decision.ranked.tier2[0].option.price_usd:.0f}"
                if decision.ranked.tier2
                else "no alternatives"
            )
        )
