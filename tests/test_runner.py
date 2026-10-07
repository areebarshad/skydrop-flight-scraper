"""End-to-end test using FixtureProvider and in-memory SQLite."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlmodel import Session, SQLModel, create_engine

from tests.conftest import make_direct_flight, make_query
from flight_alert_scraper.db.engine import migrate
from flight_alert_scraper.db.repo import get_alert_state, get_recent_runs
from flight_alert_scraper.models.alert import AlertKind
from flight_alert_scraper.notifications.base import Notifier
from flight_alert_scraper.runner import run_query
from flight_alert_scraper.scrapers.chain import ProviderChain
from flight_alert_scraper.scrapers.fixture import FixtureProvider


class _CapturingNotifier:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, recipient: str, subject: str, html_body: str, text_body: str) -> None:
        self.sent.append((recipient, subject))


@pytest.fixture()
def in_memory_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_first_run_sends_email(in_memory_session):
    flight = make_direct_flight("1100", 1200)
    chain = ProviderChain([FixtureProvider([flight])])
    notifier = _CapturingNotifier()
    query = make_query()

    run_query(query, chain, in_memory_session, notifier)
    assert len(notifier.sent) == 1


def test_second_identical_run_suppressed(in_memory_session):
    flight = make_direct_flight("1100", 1200)
    chain = ProviderChain([FixtureProvider([flight])])
    notifier = _CapturingNotifier()
    query = make_query()

    run_query(query, chain, in_memory_session, notifier)
    run_query(query, chain, in_memory_session, notifier)

    assert len(notifier.sent) == 1

    state = get_alert_state(in_memory_session, query.query_key)
    assert state is not None
    assert state.last_suppressed_reason == "unchanged"


def test_scrape_run_recorded(in_memory_session):
    flight = make_direct_flight("1100", 1200)
    chain = ProviderChain([FixtureProvider([flight])])
    query = make_query()

    run_query(query, chain, in_memory_session, None)

    runs = get_recent_runs(in_memory_session, query.query_key)
    assert len(runs) == 1
    assert runs[0].status == "ok"
    assert runs[0].tier1_count == 1
