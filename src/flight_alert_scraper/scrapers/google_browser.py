"""Browser fallback scraper using patchright (stealth Chromium)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from flight_alert_scraper.models.flight import FlightOption
from flight_alert_scraper.models.query import SearchQuery
from flight_alert_scraper.parsers.google import parse_html
from flight_alert_scraper.scrapers.base import BlockedError, ParseError
from flight_alert_scraper.scrapers.tfs import build_url

log = logging.getLogger(__name__)

_USER_DATA = Path(".cache/browser_profile")
_ARTIFACTS = Path("artifacts")


async def _fetch_async(url: str) -> tuple[str, bytes]:
    from patchright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=str(_USER_DATA),
            headless=True,
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.route(
            "**/*.{png,jpg,jpeg,gif,webp,woff,woff2,ttf,otf,mp4,mp3}",
            lambda route: route.abort(),
        )
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_selector("[data-gs], .pIav2d, .yR1fYc", timeout=15000)
        except Exception:
            pass
        html = await page.content()
        screenshot = await page.screenshot()
        await browser.close()
        return html, screenshot


class GoogleBrowserProvider:
    name = "google_browser"

    def available(self) -> bool:
        return True

    def search(self, query: SearchQuery) -> list[FlightOption]:
        url = build_url(query)
        log.info("google_browser fetching %s", url)
        html, screenshot = asyncio.run(_fetch_async(url))
        scraped_at = datetime.now(tz=timezone.utc)

        ts = scraped_at.strftime("%Y%m%dT%H%M%SZ")
        artifact_dir = _ARTIFACTS / ts
        artifact_dir.mkdir(parents=True, exist_ok=True)

        try:
            results = parse_html(html, query, scraped_at)
        except (BlockedError, ParseError):
            (artifact_dir / "browser_screenshot.png").write_bytes(screenshot)
            (artifact_dir / "browser_page.html").write_text(html)
            raise

        log.info("google_browser found %d results", len(results))
        return results
