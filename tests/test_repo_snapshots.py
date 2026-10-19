"""Round-trip tests for save_snapshots and read helpers."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlmodel import Session, SQLModel, create_engine

from flight_alert_scraper.db.repo import (
    get_price_history,
    get_snapshots_for_run,
    save_snapshots,
    start_run,
    upsert_watched_query,
)
from flight_alert_scraper.engine.ranking import rank
from tests.conftest import make_direct_flight, make_query


@pytest.fixture()
def mem_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_ranked(price: str = "1100", duration: int = 1200):
    flight = make_direct_flight(price, duration)
    query = make_query()
    return rank([flight], query), query


def test_round_trip(mem_session: Session) -> None:
    ranked, query = _make_ranked()
    upsert_watched_query(mem_session, query)
    run = start_run(mem_session, query.query_key)
    now = datetime.now(tz=UTC)
    assert run.id is not None
    save_snapshots(mem_session, run.id, query.query_key, ranked, now)

    snaps = get_snapshots_for_run(mem_session, run.id)
    assert len(snaps) == 1
    assert snaps[0].price_usd == Decimal("1100")
    assert snaps[0].tier == 1


def test_decimal_precision(mem_session: Session) -> None:
    ranked, query = _make_ranked(price="1099.99")
    upsert_watched_query(mem_session, query)
    run = start_run(mem_session, query.query_key)
    now = datetime.now(tz=UTC)
    assert run.id is not None
    save_snapshots(mem_session, run.id, query.query_key, ranked, now)

    snaps = get_snapshots_for_run(mem_session, run.id)
    assert snaps[0].price_usd == Decimal("1099.99")


def test_tier2_tier3_overlap_collapses(mem_session: Session) -> None:
    f1 = make_direct_flight("1280", 1200)
    f2 = make_direct_flight("1400", 1200)
    query = make_query(max_price="1200.00")
    ranked = rank([f1, f2], query)
    assert not ranked.tier1

    upsert_watched_query(mem_session, query)
    run = start_run(mem_session, query.query_key)
    now = datetime.now(tz=UTC)
    assert run.id is not None
    save_snapshots(mem_session, run.id, query.query_key, ranked, now)

    snaps = get_snapshots_for_run(mem_session, run.id)
    sigs = [s.signature for s in snaps]
    assert len(sigs) == len(set(sigs)), "duplicate signatures found"


def test_price_history(mem_session: Session) -> None:
    query = make_query()
    upsert_watched_query(mem_session, query)
    now = datetime.now(tz=UTC)

    for price in ["1100", "1050", "1150"]:
        flight = make_direct_flight(price, 1200)
        ranked = rank([flight], query)
        run = start_run(mem_session, query.query_key)
        assert run.id is not None
        save_snapshots(mem_session, run.id, query.query_key, ranked, now)

    history = get_price_history(mem_session, query.query_key)
    assert len(history) == 3
    assert all(h["tier1_count"] == 1 for h in history)
