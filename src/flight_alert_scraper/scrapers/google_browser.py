"""Browser fallback scraper using patchright (stealth Chromium)."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flight_alert_scraper.models.flight import FlightOption
from flight_alert_scraper.models.query import SearchQuery
from flight_alert_scraper.parsers.google import PageState, classify_page, parse_html
from flight_alert_scraper.scrapers.base import (
    BlockedError,
    NoResultsError,
    ParseError,
    RenderTimeoutError,
)
from flight_alert_scraper.scrapers.tfs import build_url

log = logging.getLogger(__name__)

_USER_DATA = Path(".cache/browser_profile")
_ARTIFACTS = Path("artifacts")

# Primary class-based selectors + aria-label fallback that survives class churn
_CARD_SELECTOR = "li.pIav2d, .yR1fYc, [aria-label*='US dollars']"


async def _fetch_async(
    url: str,
    fresh_context: bool = False,
    *,
    headless: bool,
    block_assets: bool,
    channel: str,
    wait_seconds: int,
    proxy: dict[str, Any] | None,
) -> tuple[str, bytes, list[tuple[str, int, int]], PageState]:
    """Fetch URL, return (html, screenshot, network_log, page_state)."""
    from patchright.async_api import async_playwright

    async with async_playwright() as p:
        launch_kwargs: dict[str, Any] = {"headless": headless}
        if channel:
            launch_kwargs["channel"] = channel
        if proxy:
            launch_kwargs["proxy"] = proxy

        if fresh_context:
            browser = await p.chromium.launch(**launch_kwargs)
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
            page = await ctx.new_page()
            own_browser = browser
        else:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(_USER_DATA),
                **launch_kwargs,
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            own_browser = None

        # Capture results-relevant XHRs for post-failure diagnostics
        network_log: list[tuple[str, int, int]] = []
        cap_tasks: list[asyncio.Task[None]] = []

        async def _capture(response: Any) -> None:
            u = response.url
            if "batchexecute" in u or "GetShoppingResults" in u:
                try:
                    body = await response.body()
                    network_log.append((u, response.status, len(body)))
                except Exception:
                    network_log.append((u, response.status, -1))

        def _on_response(response: Any) -> None:
            cap_tasks.append(asyncio.ensure_future(_capture(response)))

        page.on("response", _on_response)

        if block_assets:
            await page.route(
                "**/*.{png,jpg,jpeg,gif,webp,woff,woff2,ttf,otf,mp4,mp3}",
                lambda route: route.abort(),
            )

        await page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # Let the initial XHR batch settle (flight data arrives via batchexecute)
        try:
            await page.wait_for_load_state("networkidle", timeout=9000)
        except Exception:
            pass  # timeout is normal on heavy pages; continue

        # Polling wait loop — check for cards every second, nudge/retry every 5 s
        deadline = asyncio.get_event_loop().time() + wait_seconds
        page_state: PageState = "not_rendered"
        ticks = 0
        _search_triggered = False
        _reload_clicked = False

        while asyncio.get_event_loop().time() < deadline:
            count = await page.locator(_CARD_SELECTOR).count()
            if count > 0:
                await page.wait_for_timeout(1500)
                page_state = "results"
                break

            if ticks % 5 == 0:
                html_snap = await page.content()
                snap_state = classify_page(html_snap)
                if snap_state in ("no_results", "blocked"):
                    page_state = snap_state
                    break

                # Detect Google's "something went wrong" error state and click Reload
                # to retry the flight data XHR — this appears when the data request fails
                if not _reload_clicked and ticks >= 5:
                    try:
                        reload_btn = page.locator('button:text("Reload")')
                        if await reload_btn.count() > 0:
                            log.info("google_browser: clicking Reload button at tick %d", ticks)
                            await reload_btn.first.click()
                            _reload_clicked = True
                            await page.wait_for_timeout(6000)
                    except Exception:
                        pass

                try:
                    await page.evaluate("window.scrollBy(0, 400)")
                    await page.wait_for_timeout(300)
                except Exception:
                    pass

            # After 15 s still no cards: press Enter to re-trigger search
            if ticks == 15 and not _search_triggered:
                _search_triggered = True
                try:
                    await page.keyboard.press("Enter")
                    await page.wait_for_timeout(2000)
                    # Also try clicking any visible search/explore button
                    for btn_sel in ('[aria-label*="Search"]', '[jsname="vLv7Lb"]'):
                        btn = page.locator(btn_sel).first
                        if await btn.count() > 0:
                            await btn.click()
                            await page.wait_for_timeout(2000)
                            break
                except Exception:
                    pass

            await page.wait_for_timeout(1000)
            ticks += 1

        html = await page.content()
        screenshot = await page.screenshot()

        if cap_tasks:
            await asyncio.gather(*cap_tasks, return_exceptions=True)

        await ctx.close()
        if own_browser:
            await own_browser.close()

        return html, screenshot, network_log, page_state


class GoogleBrowserProvider:
    name = "google_browser"

    def available(self) -> bool:
        return True

    def search(self, query: SearchQuery) -> list[FlightOption]:
        from flight_alert_scraper.config import get_settings
        from flight_alert_scraper.scrapers.proxy import next_proxy

        settings = get_settings()
        url = build_url(query)
        log.info("google_browser fetching %s", url)

        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        artifact_dir = _ARTIFACTS / ts

        fetch_kwargs: dict[str, Any] = {
            "headless": settings.browser_headless,
            "block_assets": settings.browser_block_assets,
            "channel": settings.browser_channel,
            "wait_seconds": settings.browser_wait_seconds,
            "proxy": next_proxy(),
        }

        html, screenshot, network_log, page_state = asyncio.run(
            _fetch_async(url, fresh_context=False, **fetch_kwargs)
        )
        scraped_at = datetime.now(tz=UTC)

        def _save_failure(
            label: str, h: str, shot: bytes, nl: list[tuple[str, int, int]]
        ) -> None:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / f"{label}.html").write_text(h, encoding="utf-8")
            (artifact_dir / f"{label}_screenshot.png").write_bytes(shot)
            if nl:
                lines = "\n".join(f"{u} {s} {sz}" for u, s, sz in nl)
                (artifact_dir / "network.log").write_text(lines, encoding="utf-8")

        if page_state == "blocked":
            _save_failure("browser_blocked", html, screenshot, network_log)
            raise BlockedError("Google consent/block wall in browser")

        if page_state == "no_results":
            _save_failure("browser_no_results", html, screenshot, network_log)
            raise NoResultsError(
                "Google returned no results (browser, persistent context)"
            )

        if page_state == "not_rendered":
            # Persistent profile may be stale/flagged — retry with a clean context
            log.warning(
                "google_browser: not_rendered after %ds, retrying fresh",
                settings.browser_wait_seconds,
            )
            _save_failure("browser_not_rendered", html, screenshot, network_log)

            html2, screenshot2, network_log2, page_state2 = asyncio.run(
                _fetch_async(url, fresh_context=True, **fetch_kwargs)
            )

            if page_state2 == "blocked":
                _save_failure("browser_fresh_blocked", html2, screenshot2, network_log2)
                raise BlockedError("Google consent/block wall (fresh browser context)")

            if page_state2 == "no_results":
                _save_failure(
                    "browser_fresh_no_results", html2, screenshot2, network_log2
                )
                raise NoResultsError(
                    "Google returned no results (browser, fresh context)"
                )

            if page_state2 == "not_rendered":
                _save_failure(
                    "browser_fresh_not_rendered", html2, screenshot2, network_log2
                )
                raise RenderTimeoutError(
                    f"Page did not render after {settings.browser_wait_seconds}s "
                    "(both persistent and fresh context)"
                )

            html, screenshot = html2, screenshot2

        # page_state is "results"
        try:
            results = parse_html(html, query, scraped_at)
        except (BlockedError, ParseError):
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "browser_parse_error.html").write_text(
                html, encoding="utf-8"
            )
            (artifact_dir / "browser_parse_error_screenshot.png").write_bytes(
                screenshot
            )
            raise

        log.info("google_browser found %d results", len(results))
        return results
