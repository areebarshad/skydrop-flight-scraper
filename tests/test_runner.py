"""End-to-end test using FixtureProvider and in-memory SQLite."""
from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine

from flight_alert_scraper.db.repo import get_alert_state, get_recent_runs
from flight_alert_scraper.runner import run_query
from flight_alert_scraper.scrapers.chain import ProviderChain
from flight_alert_scraper.scrapers.fixture import FixtureProvider
from tests.conftest import make_direct_flight, make_query  # noqa: F401


class _CapturingNotifier:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(
        self, recipient: str, subject: str, html_body: str, text_body: str
    ) -> None:
        self.sent.append((recipient, subject))


@pytest.fixture()
def in_memory_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
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


def test_snapshots_written_after_run(in_memory_session):
    from flight_alert_scraper.db.repo import get_latest_run, get_snapshots_for_run

    flight = make_direct_flight("1100", 1200)
    chain = ProviderChain([FixtureProvider([flight])])
    query = make_query()

    run_query(query, chain, in_memory_session, None)

    latest = get_latest_run(in_memory_session, query.query_key)
    assert latest is not None
    assert latest.id is not None
    snaps = get_snapshots_for_run(in_memory_session, latest.id)
    assert len(snaps) >= 1


def test_render_timeout_chain_outcome() -> None:
    """RenderTimeoutError from all providers → chain.outcome == 'failed'."""
    from flight_alert_scraper.scrapers.base import RenderTimeoutError

    class _TimeoutProvider:
        name = "timeout_fixture"

        def available(self) -> bool:
            return True

        def search(self, query):
            raise RenderTimeoutError("simulated timeout")

    chain = ProviderChain([_TimeoutProvider()])
    _, metrics = chain.search(make_query())
    assert metrics.outcome == "failed"


def test_render_timeout_recorded_as_error(in_memory_session) -> None:
    """RenderTimeoutError → run.status == 'error', not 'ok'."""
    from flight_alert_scraper.scrapers.base import RenderTimeoutError

    class _TimeoutProvider:
        name = "timeout_fixture"

        def available(self) -> bool:
            return True

        def search(self, query):
            raise RenderTimeoutError("simulated timeout")

    chain = ProviderChain([_TimeoutProvider()])
    query = make_query()
    run_query(query, chain, in_memory_session, None)

    runs = get_recent_runs(in_memory_session, query.query_key)
    assert len(runs) == 1
    assert runs[0].status == "error"


def test_no_results_chain_outcome() -> None:
    """NoResultsError from all providers → chain.outcome == 'no_results'."""
    from flight_alert_scraper.scrapers.base import NoResultsError

    class _NoResultsProvider:
        name = "no_results_fixture"

        def available(self) -> bool:
            return True

        def search(self, query):
            raise NoResultsError("simulated no results")

    chain = ProviderChain([_NoResultsProvider()])
    _, metrics = chain.search(make_query())
    assert metrics.outcome == "no_results"


def test_no_results_recorded_as_no_results(in_memory_session) -> None:
    """NoResultsError → run.status == 'no_results'."""
    from flight_alert_scraper.scrapers.base import NoResultsError

    class _NoResultsProvider:
        name = "no_results_fixture"

        def available(self) -> bool:
            return True

        def search(self, query):
            raise NoResultsError("simulated no results")

    chain = ProviderChain([_NoResultsProvider()])
    query = make_query()
    run_query(query, chain, in_memory_session, None)

    runs = get_recent_runs(in_memory_session, query.query_key)
    assert len(runs) == 1
    assert runs[0].status == "no_results"


def test_snapshot_failure_does_not_break_run(in_memory_session):
    """A broken save_snapshots must not prevent the run from completing."""
    import unittest.mock as mock

    flight = make_direct_flight("1100", 1200)
    chain = ProviderChain([FixtureProvider([flight])])
    query = make_query()

    with mock.patch(
        "flight_alert_scraper.db.repo.save_snapshots",
        side_effect=RuntimeError("boom"),
    ):
        run_query(query, chain, in_memory_session, None)

    runs = get_recent_runs(in_memory_session, query.query_key)
    assert runs[0].status == "ok"
