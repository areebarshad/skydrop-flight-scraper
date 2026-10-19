from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Literal, TypedDict

log = logging.getLogger(__name__)

JobState = Literal["pending", "running", "done", "error"]


class JobStatus(TypedDict):
    job_id: str
    query_key: str
    state: JobState
    started_at: datetime
    message: str


_lock = threading.Lock()
_jobs: dict[str, JobStatus] = {}
_active: dict[str, str] = {}


def start_check(query_key: str) -> str:
    with _lock:
        existing = _active.get(query_key)
        if existing:
            j = _jobs.get(existing)
            if j and j["state"] in ("pending", "running"):
                return existing
        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = JobStatus(
            job_id=job_id,
            query_key=query_key,
            state="pending",
            started_at=datetime.now(tz=UTC),
            message="Queued",
        )
        _active[query_key] = job_id
    t = threading.Thread(target=_worker, args=(job_id, query_key), daemon=True)
    t.start()
    return job_id


def get_job(job_id: str) -> JobStatus | None:
    return _jobs.get(job_id)


def _worker(job_id: str, query_key: str) -> None:
    with _lock:
        _jobs[job_id]["state"] = "running"
        _jobs[job_id]["message"] = "Scraping…"
    try:
        from flight_alert_scraper.config import get_settings
        from flight_alert_scraper.db.engine import get_session
        from flight_alert_scraper.runner import run_query
        from flight_alert_scraper.scrapers.chain import ProviderChain
        from flight_alert_scraper.scrapers.google_browser import GoogleBrowserProvider
        from flight_alert_scraper.scrapers.google_http import GoogleHttpProvider
        from flight_alert_scraper.scrapers.serpapi import SerpApiProvider

        settings = get_settings()
        queries = settings.load_queries()
        query = next((q for q in queries if q.query_key == query_key), None)
        if query is None:
            raise ValueError(f"query_key {query_key!r} not in watchlist")

        from flight_alert_scraper.scrapers.base import FlightProvider

        providers: list[FlightProvider] = [
            GoogleHttpProvider(),
            GoogleBrowserProvider(),
        ]
        if settings.serpapi_key:
            providers.append(SerpApiProvider(settings.serpapi_key))
        chain = ProviderChain(providers)

        notifier = None
        if settings.smtp_user and settings.smtp_app_password:
            from flight_alert_scraper.notifications.smtp import SmtpNotifier

            notifier = SmtpNotifier(settings.smtp_user, settings.smtp_app_password)

        with get_session(settings.db_path) as session:
            run_query(query, chain, session, notifier)

        with _lock:
            _jobs[job_id]["state"] = "done"
            _jobs[job_id]["message"] = "Done"
    except Exception as exc:
        log.exception("Background job %s failed", job_id)
        with _lock:
            _jobs[job_id]["state"] = "error"
            _jobs[job_id]["message"] = str(exc)[:200]
