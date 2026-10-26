"""Browser fallback scraper using patchright (stealth Chromium)."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from flight_alert_scraper.models.flight import FlightOption
from flight_alert_scraper.models.query import SearchQuery
from flight_alert_scraper.parsers.google import parse_html
from flight_alert_scraper.scrapers.base import BlockedError, ParseError
from flight_alert_scraper.scrapers.tfs import build_url

log = logging.getLogger(__name__)

_USER_DATA = Path(".cache/browser_profile")
_ARTIFACTS = Path("artifacts")

# Flight card selectors — no data-gs (that attribute is gone from current Google DOM)
_CARD_SELECTOR = "li.pIav2d, .yR1fYc"


async def _fetch_async(url: str, fresh_context: bool = False) -> tuple[str, bytes]:
    from patchright.async_api import async_playwright

    async with async_playwright() as p:
        if fresh_context:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
            page = await ctx.new_page()
            own_browser = browser
        else:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(_USER_DATA),
                headless=True,
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            own_browser = None

        await page.route(
            "**/*.{png,jpg,jpeg,gif,webp,woff,woff2,ttf,otf,mp4,mp3}",
            lambda route: route.abort(),
        )
        await page.goto(url, wait_until="load", timeout=60000)
        try:
            await page.wait_for_selector(_CARD_SELECTOR, timeout=25000)
            # Extra dwell time so dynamic price data can fully render
            await page.wait_for_timeout(2000)
        except Exception:
            pass
        # Scroll down to trigger lazy-loaded results
        try:
            await page.evaluate("window.scrollBy(0, 400)")
            await page.wait_for_timeout(1500)
        except Exception:
            pass
        html = await page.content()
        screenshot = await page.screenshot()
        await ctx.close()
        if own_browser:
            await own_browser.close()
        return html, screenshot


class GoogleBrowserProvider:
    name = "google_browser"

    def available(self) -> bool:
        return True

    def search(self, query: SearchQuery) -> list[FlightOption]:
        url = build_url(query)
        log.info("google_browser fetching %s", url)
        html, screenshot = asyncio.run(_fetch_async(url, fresh_context=False))
        scraped_at = datetime.now(tz=UTC)

        ts = scraped_at.strftime("%Y%m%dT%H%M%SZ")
        artifact_dir = _ARTIFACTS / ts
        artifact_dir.mkdir(parents=True, exist_ok=True)

        try:
            results = parse_html(html, query, scraped_at)
        except (BlockedError, ParseError):
            (artifact_dir / "browser_screenshot.png").write_bytes(screenshot)
            (artifact_dir / "browser_page.html").write_text(html, encoding="utf-8")
            raise

        if not results:
            # Persistent profile may be stale/flagged — save for debug and retry
            # with a fresh (non-persistent) browser context.
            log.warning(
                "google_browser persistent profile returned 0 results, "
                "saving HTML and retrying with fresh context"
            )
            (artifact_dir / "browser_zero_results.html").write_text(html, encoding="utf-8")

            html2, screenshot2 = asyncio.run(_fetch_async(url, fresh_context=True))
            try:
                results = parse_html(html2, query, scraped_at)
            except (BlockedError, ParseError):
                (artifact_dir / "browser_fresh_page.html").write_text(html2, encoding="utf-8")
                raise
            if not results:
                (artifact_dir / "browser_fresh_zero.html").write_text(html2, encoding="utf-8")

        log.info("google_browser found %d results", len(results))
        return results
