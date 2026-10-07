from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from flight_alert_scraper.db.tables import AlertLog, AlertState, ScrapeRun, WatchedQuery
from flight_alert_scraper.models.query import SearchQuery
from flight_alert_scraper.models.result import RankedResults


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
        created_at=datetime.now(tz=timezone.utc),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def start_run(session: Session, query_key: str) -> ScrapeRun:
    run = ScrapeRun(query_key=query_key, started_at=datetime.now(tz=timezone.utc))
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
    run.finished_at = datetime.now(tz=timezone.utc)
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


def get_recent_runs(session: Session, query_key: str, limit: int = 10) -> list[ScrapeRun]:
    stmt = (
        select(ScrapeRun)
        .where(ScrapeRun.query_key == query_key)
        .order_by(ScrapeRun.started_at.desc())  # type: ignore[union-attr]
        .limit(limit)
    )
    return list(session.exec(stmt).all())
