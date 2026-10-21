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
    ScrapeRun,
    UserSetting,
    WatchedQuery,
)
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
) -> None:
    best: dict[str, TieredMatch] = {}
    for match in ranked.tier1 + ranked.tier2 + ranked.tier3:
        sig = match.option.signature
        if sig not in best or int(match.tier) < int(best[sig].tier):
            best[sig] = match
    for match in best.values():
        carriers = ",".join(
            dict.fromkeys(leg.carrier_code for leg in match.option.legs)
        )
        snap = FlightSnapshot(
            run_id=run_id,
            query_key=query_key,
            signature=match.option.signature,
            price_usd=match.option.price_usd,
            total_duration_minutes=match.option.total_duration_minutes,
            stops=match.option.stops,
            carriers=carriers,
            tier=int(match.tier),
            labels=json.dumps([str(lbl) for lbl in match.labels]),
            effective_cost_usd=match.effective_cost_usd,
            option_json=match.option.model_dump_json(),
            observed_at=observed_at,
        )
        session.add(snap)
    session.commit()


def list_watched_queries(session: Session) -> list[WatchedQuery]:
    stmt = select(WatchedQuery).where(WatchedQuery.active == True)  # noqa: E712
    return list(session.exec(stmt).all())


def get_latest_run(session: Session, query_key: str) -> ScrapeRun | None:
    stmt = (
        select(ScrapeRun)
        .where(ScrapeRun.query_key == query_key, ScrapeRun.status == "ok")
        .order_by(ScrapeRun.started_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    )
    return session.exec(stmt).first()


def get_snapshots_for_run(session: Session, run_id: int) -> list[FlightSnapshot]:
    stmt = (
        select(FlightSnapshot)
        .where(FlightSnapshot.run_id == run_id)
        .order_by(FlightSnapshot.tier, FlightSnapshot.price_usd)  # type: ignore[arg-type]
    )
    return list(session.exec(stmt).all())


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


def deactivate_watched_query(session: Session, query_key: str) -> None:
    wq = session.get(WatchedQuery, query_key)
    if wq:
        wq.active = False
        session.add(wq)
        session.commit()
