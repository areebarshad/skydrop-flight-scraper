"""Primary scraper: httpx + selectolax against Google Flights."""
from __future__ import annotations

import gzip
import json
import logging
import random
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from flight_alert_scraper.models.flight import FlightOption
from flight_alert_scraper.models.query import SearchQuery
from flight_alert_scraper.parsers.google import classify_page, parse_html
from flight_alert_scraper.scrapers.base import (
    BlockedError,
    NoResultsError,
    ParseError,
    RenderTimeoutError,
    TransientError,
)
from flight_alert_scraper.scrapers.tfs import build_url

log = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_COOKIE_JAR = Path(".cache/cookies.json")
_ARTIFACTS = Path("artifacts")


def _load_cookies() -> dict[str, str]:
    if _COOKIE_JAR.exists():
        try:
            data: dict[str, str] = json.loads(_COOKIE_JAR.read_text())
            return data
        except Exception:
            pass
    return {"CONSENT": "YES+cb.20210720-07-p0.en+FX+410"}


def _save_cookies(jar: httpx.Cookies) -> None:
    _COOKIE_JAR.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, str] = {}
    for cookie in jar.jar:  # iterate the underlying http.cookiejar.CookieJar
        if cookie.value is not None:
            data[cookie.name] = cookie.value
    _COOKIE_JAR.write_text(json.dumps(data))


def _save_artifact(html: str, label: str) -> None:
    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = _ARTIFACTS / ts
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{label}.html.gz"
    path.write_bytes(gzip.compress(html.encode()))
    log.debug("Saved artifact to %s", path)


class GoogleHttpProvider:
    name = "google_http"

    def __init__(self) -> None:
        self._client: httpx.Client | None = None

    def available(self) -> bool:
        return True

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            from flight_alert_scraper.scrapers.proxy import next_proxy

            cookies = _load_cookies()
            proxy_cfg = next_proxy()
            proxy_url: str | None = proxy_cfg["server"] if proxy_cfg else None
            self._client = httpx.Client(
                headers={
                    "User-Agent": _UA,
                    "Accept-Language": "en-US,en;q=0.9",
                },
                cookies=cookies,
                http2=True,
                follow_redirects=True,
                timeout=30,
                proxy=proxy_url,
            )
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _fetch(self, url: str) -> str:
        client = self._get_client()
        time.sleep(random.uniform(2, 6))
        resp = client.get(url)
        _save_cookies(client.cookies)
        if resp.status_code == 429:
            raise TransientError(f"429 Too Many Requests from {url}")
        if resp.status_code >= 500:
            raise TransientError(f"HTTP {resp.status_code} from {url}")
        if resp.status_code >= 400:
            raise BlockedError(f"HTTP {resp.status_code} from {url}")
        body = resp.text
        snippet = body[:2048].lower()
        if "<html" not in snippet and "<!doctype" not in snippet:
            enc = resp.headers.get("content-encoding", "none")
            raise ParseError(f"response body is not HTML (Content-Encoding: {enc})")
        return body

    def search(self, query: SearchQuery) -> list[FlightOption]:
        url = build_url(query)
        log.info("google_http fetching %s", url)
        html = self._fetch(url)
        _save_artifact(html, "response")
        scraped_at = datetime.now(tz=UTC)
        try:
            results = parse_html(html, query, scraped_at)
        except ParseError:
            _save_artifact(html, "parse_error")
            raise
        if not results:
            state = classify_page(html)
            if state == "no_results":
                raise NoResultsError(f"Google HTTP: no results (state={state})")
            raise RenderTimeoutError(f"Google HTTP: page not rendered (state={state})")
        log.info("google_http found %d results", len(results))
        return results
