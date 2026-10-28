from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TypedDict

from sqlmodel import Session, select

from flight_alert_scraper.db.tables import (
    AlertLog,
    AlertState,
    FlightSnapshot,
    RunStats,
    ScrapeRun,
    UserSetting,
    WatchedQuery,
)
from flight_alert_scraper.engine.scoring import effective_cost
from flight_alert_scraper.models.flight import FlightOption
from flight_alert_scraper.models.query import SearchQuery
from flight_alert_scraper.models.result import RankedResults, TieredMatch


class PriceHistoryPoint(TypedDict):
    run_id: int
    observed_at: datetime
    min_tier1_price: Decimal | None
    min_overall_price: Decimal
    tier1_count: int


def upsert_watched_query(session: Session, query: SearchQuery) -> WatchedQuery:
    existing = session.get(WatchedQuery, query.query_key)
    if existing:
        return existing
    row = WatchedQuery(
        query_key=query.query_key,
        origin=query.origin,
        destination=query.destination,
        depart_date=query.depart_date.isoformat(),
        return_date=query.return_date.isoformat() if query.return_date else None,
        cabin=query.cabin,
        adults=query.adults,
        constraints_json=query.constraints.model_dump_json(),
        created_at=datetime.now(tz=UTC),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def start_run(session: Session, query_key: str) -> ScrapeRun:
    run = ScrapeRun(query_key=query_key, started_at=datetime.now(tz=UTC))
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def finish_run(
    session: Session,
    run: ScrapeRun,
    ranked: RankedResults | None,
    provider: str | None,
    status: str,
    error: str | None = None,
) -> None:
    run.finished_at = datetime.now(tz=UTC)
    run.provider = provider
    run.status = status
    run.error_message = error
    if ranked:
        run.candidates_found = ranked.total_candidates
        run.tier1_count = len(ranked.tier1)
        run.tier2_count = len(ranked.tier2)
    session.add(run)

    wq = session.get(WatchedQuery, run.query_key)
    if wq:
        wq.last_checked_at = run.finished_at
        session.add(wq)

    session.commit()


def get_alert_state(session: Session, query_key: str) -> AlertState | None:
    return session.get(AlertState, query_key)


def save_alert_state(session: Session, state: AlertState) -> None:
    existing = session.get(AlertState, state.query_key)
    if existing is not None:
        for field, value in state.model_dump().items():
            setattr(existing, field, value)
        session.add(existing)
    else:
        session.add(state)
    session.commit()


def log_alert(session: Session, entry: AlertLog) -> None:
    session.add(entry)
    session.commit()


def alert_already_sent(session: Session, payload_hash: str, query_key: str) -> bool:
    stmt = select(AlertLog).where(
        AlertLog.query_key == query_key,
        AlertLog.payload_hash == payload_hash,
        AlertLog.delivery_ok == True,  # noqa: E712
    )
    return session.exec(stmt).first() is not None


def get_recent_runs(
    session: Session, query_key: str, limit: int = 10
) -> list[ScrapeRun]:
    stmt = (
        select(ScrapeRun)
        .where(ScrapeRun.query_key == query_key)
        .order_by(ScrapeRun.started_at.desc())  # type: ignore[attr-defined]
        .limit(limit)
    )
    return list(session.exec(stmt).all())


def save_snapshots(
    session: Session,
    run_id: int,
    query_key: str,
    ranked: RankedResults,
    observed_at: datetime,
    all_options: list[FlightOption] | None = None,
) -> None:
    # Build dict of ranked matches: signature → (tier, labels, effective_cost, option)
    tiered: dict[str, TieredMatch] = {}
    for match in ranked.tier1 + ranked.tier2 + ranked.tier3:
        sig = match.option.signature
        if sig not in tiered or int(match.tier) < int(tiered[sig].tier):
            tiered[sig] = match

    # Collect every option to persist (ranked + any raw candidates not already tiered)
    to_save: dict[str, tuple[FlightOption, int, list[str], object]] = {}
    for match in tiered.values():
        to_save[match.option.signature] = (
            match.option,
            int(match.tier),
            [str(lbl) for lbl in match.labels],
            match.effective_cost_usd,
        )

    if all_options:
        k = ranked.query.constraints.hourly_time_penalty_usd
        # Dedupe by signature (keep lowest price per signature)
        raw: dict[str, FlightOption] = {}
        for opt in all_options:
            if opt.signature not in to_save:
                if opt.signature not in raw or opt.price_usd < raw[opt.signature].price_usd:
                    raw[opt.signature] = opt
        for sig, opt in raw.items():
            to_save[sig] = (opt, 0, [], effective_cost(opt, k))

    for sig, (opt, tier, labels, ec) in to_save.items():
        carriers = ",".join(dict.fromkeys(leg.carrier_code for leg in opt.legs))
        snap = FlightSnapshot(
            run_id=run_id,
            query_key=query_key,
            signature=sig,
            price_usd=opt.price_usd,
            total_duration_minutes=opt.total_duration_minutes,
            stops=opt.stops,
            carriers=carriers,
            tier=tier,
            labels=json.dumps(labels),
            effective_cost_usd=ec,
            option_json=opt.model_dump_json(),
            observed_at=observed_at,
        )
        session.add(snap)
    session.commit()


def list_watched_queries(session: Session) -> list[WatchedQuery]:
    stmt = select(WatchedQuery).where(WatchedQuery.active == True)  # noqa: E712
    return list(session.exec(stmt).all())


def get_latest_run(
    session: Session, query_key: str, require_ok: bool = True
) -> ScrapeRun | None:
    stmt = select(ScrapeRun).where(ScrapeRun.query_key == query_key)
    if require_ok:
        stmt = stmt.where(ScrapeRun.status == "ok")
    stmt = stmt.order_by(ScrapeRun.started_at.desc()).limit(1)  # type: ignore[attr-defined]
    return session.exec(stmt).first()


def get_snapshots_for_run(session: Session, run_id: int) -> list[FlightSnapshot]:
    stmt = (
        select(FlightSnapshot)
        .where(FlightSnapshot.run_id == run_id)
        .order_by(FlightSnapshot.tier, FlightSnapshot.price_usd)  # type: ignore[arg-type]
    )
    return list(session.exec(stmt).all())


def get_cheapest_carrier_by_run(
    session: Session, run_ids: list[int]
) -> dict[int, str]:
    if not run_ids:
        return {}
    stmt = (
        select(FlightSnapshot)
        .where(FlightSnapshot.run_id.in_(run_ids))  # type: ignore[attr-defined]
        .order_by(FlightSnapshot.run_id, FlightSnapshot.price_usd)  # type: ignore[arg-type]
    )
    result: dict[int, str] = {}
    for snap in session.exec(stmt).all():
        if snap.run_id not in result:
            try:
                opt = json.loads(snap.option_json)
                seen: list[str] = []
                for leg in opt.get("legs", []):
                    name = leg.get("carrier") or leg.get("carrier_code", "")
                    if name and name not in seen:
                        seen.append(name)
                result[snap.run_id] = " · ".join(seen) if seen else snap.carriers
            except Exception:
                result[snap.run_id] = snap.carriers
    return result


def get_price_history(
    session: Session, query_key: str, limit: int = 90
) -> list[PriceHistoryPoint]:
    stmt = (
        select(FlightSnapshot)
        .where(FlightSnapshot.query_key == query_key)
        .order_by(FlightSnapshot.observed_at)  # type: ignore[arg-type]
    )
    snaps = list(session.exec(stmt).all())

    by_run: dict[int, list[FlightSnapshot]] = {}
    for snap in snaps:
        by_run.setdefault(snap.run_id, []).append(snap)

    sorted_run_ids = sorted(by_run.keys(), key=lambda rid: by_run[rid][0].observed_at)
    sorted_run_ids = sorted_run_ids[-limit:]

    result: list[PriceHistoryPoint] = []
    for run_id in sorted_run_ids:
        run_snaps = by_run[run_id]
        tier1_prices = [s.price_usd for s in run_snaps if s.tier == 1]
        all_prices = [s.price_usd for s in run_snaps]
        result.append(
            PriceHistoryPoint(
                run_id=run_id,
                observed_at=run_snaps[0].observed_at,
                min_tier1_price=min(tier1_prices) if tier1_prices else None,
                min_overall_price=min(all_prices),
                tier1_count=len(tier1_prices),
            )
        )
    return result


def get_cheapest_price_by_run(
    session: Session, run_ids: list[int]
) -> dict[int, Decimal]:
    if not run_ids:
        return {}
    stmt = (
        select(FlightSnapshot)
        .where(FlightSnapshot.run_id.in_(run_ids))  # type: ignore[attr-defined]
        .order_by(FlightSnapshot.run_id, FlightSnapshot.price_usd)  # type: ignore[arg-type]
    )
    result: dict[int, Decimal] = {}
    for snap in session.exec(stmt).all():
        if snap.run_id not in result:
            result[snap.run_id] = snap.price_usd
    return result


def get_recent_alerts(
    session: Session, query_key: str, limit: int = 20
) -> list[AlertLog]:
    stmt = (
        select(AlertLog)
        .where(AlertLog.query_key == query_key)
        .order_by(AlertLog.sent_at.desc())  # type: ignore[attr-defined]
        .limit(limit)
    )
    return list(session.exec(stmt).all())


def get_user_setting(session: Session, key: str) -> str | None:
    row = session.get(UserSetting, key)
    return row.value if row else None


def set_user_setting(session: Session, key: str, value: str) -> None:
    existing = session.get(UserSetting, key)
    if existing is not None:
        existing.value = value
        existing.updated_at = datetime.now(tz=UTC)
        session.add(existing)
    else:
        session.add(UserSetting(key=key, value=value, updated_at=datetime.now(tz=UTC)))
    session.commit()


def get_all_snapshot_prices(session: Session, query_key: str) -> list[float]:
    """Every individual flight price ever scraped for this query (all runs, all tiers)."""
    stmt = select(FlightSnapshot.price_usd).where(FlightSnapshot.query_key == query_key)
    return [float(row) for row in session.exec(stmt).all()]


def save_run_stats(
    session: Session,
    run_id: int,
    query_key: str,
    mean_usd: Decimal,
    std_usd: Decimal,
    n_samples: int,
) -> None:
    now = datetime.now(tz=UTC)
    existing = session.exec(select(RunStats).where(RunStats.run_id == run_id)).first()
    if existing is not None:
        existing.mean_usd = mean_usd
        existing.std_usd = std_usd
        existing.n_samples = n_samples
        existing.computed_at = now
        session.add(existing)
    else:
        session.add(
            RunStats(
                run_id=run_id,
                query_key=query_key,
                mean_usd=mean_usd,
                std_usd=std_usd,
                n_samples=n_samples,
                computed_at=now,
            )
        )
    session.commit()


def deactivate_watched_query(session: Session, query_key: str) -> None:
    wq = session.get(WatchedQuery, query_key)
    if wq:
        wq.active = False
        session.add(wq)
        session.commit()
