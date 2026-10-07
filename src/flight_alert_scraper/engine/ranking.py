from __future__ import annotations

from decimal import Decimal

from flight_alert_scraper.engine.scoring import effective_cost, pareto_front
from flight_alert_scraper.models.flight import FlightOption
from flight_alert_scraper.models.query import SearchQuery
from flight_alert_scraper.models.result import MatchLabel, RankedResults, Tier, TieredMatch


def _fmt_hours(minutes: int) -> str:
    h, m = divmod(abs(minutes), 60)
    return f"{h}h {m}m" if m else f"{h}h"


def _to_match(
    option: FlightOption,
    tier: Tier,
    labels: list[MatchLabel],
    query: SearchQuery,
) -> TieredMatch:
    c = query.constraints
    k = c.hourly_time_penalty_usd
    ec = effective_cost(option, k)
    price_delta = option.price_usd - c.max_price_usd
    dur_delta = (
        option.total_duration_minutes - c.max_duration_minutes
        if c.max_duration_minutes is not None
        else 0
    )

    notes: list[str] = []
    for label in labels:
        if label == MatchLabel.DIRECT:
            notes.append(
                f"${option.price_usd:.0f}, {_fmt_hours(option.total_duration_minutes)} — meets all constraints"
            )
        elif label == MatchLabel.CHEAPEST:
            over = option.price_usd - c.max_price_usd
            notes.append(
                f"Cheapest at ${option.price_usd:.0f}"
                + (f", but ${over:.0f} over budget" if over > 0 else "")
            )
        elif label == MatchLabel.FASTEST:
            over = option.price_usd - c.max_price_usd
            notes.append(
                f"Fastest at {_fmt_hours(option.total_duration_minutes)}"
                + (f", but ${over:.0f} over budget" if over > 0 else "")
            )
        elif label == MatchLabel.BEST_BALANCE:
            notes.append(
                f"Best balance: ${option.price_usd:.0f}, "
                f"{_fmt_hours(option.total_duration_minutes)} "
                f"(eff. cost ${ec:.0f})"
            )
        elif label == MatchLabel.VALUE_DEAL:
            savings = c.max_price_usd - option.price_usd
            pct = int(savings / c.max_price_usd * 100)
            extra = option.total_duration_minutes - (c.max_duration_minutes or 0)
            notes.append(
                f"${savings:.0f} under budget (-{pct}%), "
                f"but +{_fmt_hours(extra)} over time limit"
            )
        elif label == MatchLabel.TIME_SAVER:
            over_amt = option.price_usd - c.max_price_usd
            over_pct = int(over_amt / c.max_price_usd * 100)
            notes.append(
                f"Within time limit for ${over_amt:.0f} over budget (+{over_pct}%)"
            )

    return TieredMatch(
        option=option,
        tier=tier,
        labels=labels,
        effective_cost_usd=ec,
        price_delta_usd=price_delta,
        duration_delta_minutes=dur_delta,
        tradeoff_note="; ".join(notes),
    )


def _dedupe_by_signature(options: list[FlightOption]) -> list[FlightOption]:
    seen: dict[str, FlightOption] = {}
    for o in options:
        if o.signature not in seen or o.price_usd < seen[o.signature].price_usd:
            seen[o.signature] = o
    return list(seen.values())


def rank(options: list[FlightOption], query: SearchQuery) -> RankedResults:
    c = query.constraints
    total = len(options)

    if c.max_stops is not None:
        options = [o for o in options if o.stops <= c.max_stops]
    filtered_out = total - len(options)

    options = _dedupe_by_signature(options)

    budget = c.max_price_usd
    limit = c.max_duration_minutes

    def within_budget(o: FlightOption) -> bool:
        return o.price_usd <= budget

    def within_time(o: FlightOption) -> bool:
        return limit is None or o.total_duration_minutes <= limit

    tier1_raw = sorted(
        (o for o in options if within_budget(o) and within_time(o)),
        key=lambda o: (o.price_usd, o.total_duration_minutes),
    )

    t1_sigs = {o.signature for o in tier1_raw}
    near: dict[str, list[MatchLabel]] = {}

    if limit is not None:
        value_ceiling = budget * (Decimal(1) - c.value_deal_discount)
        for o in options:
            if o.signature in t1_sigs:
                continue
            overage = o.total_duration_minutes - limit
            if o.price_usd <= value_ceiling and 0 < overage <= c.value_deal_duration_buffer_minutes:
                near.setdefault(o.signature, []).append(MatchLabel.VALUE_DEAL)

    price_ceiling = budget * (Decimal(1) + c.time_saver_price_overage)
    for o in options:
        if o.signature in t1_sigs:
            continue
        if within_time(o) and budget < o.price_usd <= price_ceiling:
            near.setdefault(o.signature, []).append(MatchLabel.TIME_SAVER)

    by_sig = {o.signature: o for o in options}
    candidates = [by_sig[s] for s in near]
    tier2 = [
        _to_match(o, Tier.NEAR_MISS, near[o.signature], query)
        for o in sorted(
            pareto_front(candidates),
            key=lambda o: effective_cost(o, c.hourly_time_penalty_usd),
        )
    ]

    tier3: list[TieredMatch] = []
    if not tier1_raw and options:
        k = c.hourly_time_penalty_usd
        best_balance = min(options, key=lambda o: (effective_cost(o, k), o.price_usd))
        cheapest = min(options, key=lambda o: (o.price_usd, o.total_duration_minutes))
        fastest = min(options, key=lambda o: (o.total_duration_minutes, o.price_usd))

        picks: dict[str, list[MatchLabel]] = {}
        for opt, label in (
            (best_balance, MatchLabel.BEST_BALANCE),
            (cheapest, MatchLabel.CHEAPEST),
            (fastest, MatchLabel.FASTEST),
        ):
            picks.setdefault(opt.signature, []).append(label)

        order = [MatchLabel.BEST_BALANCE, MatchLabel.CHEAPEST, MatchLabel.FASTEST]
        tier3 = sorted(
            (
                _to_match(by_sig[s], Tier.BASELINE, lbls, query)
                for s, lbls in picks.items()
            ),
            key=lambda m: order.index(m.labels[0]),
        )

    return RankedResults(
        query=query,
        tier1=[_to_match(o, Tier.DIRECT_MATCH, [MatchLabel.DIRECT], query) for o in tier1_raw],
        tier2=tier2,
        tier3=tier3,
        total_candidates=total,
        filtered_out=filtered_out,
    )
