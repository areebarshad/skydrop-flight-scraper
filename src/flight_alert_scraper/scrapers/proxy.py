"""Proxy helpers — parse and round-robin a proxy pool. Off by default."""
from __future__ import annotations

import itertools
from typing import TypedDict
from urllib.parse import urlparse


class ProxyConfig(TypedDict):
    server: str
    username: str
    password: str


def parse_proxy(url: str) -> ProxyConfig | None:
    """Convert scheme://user:pass@host:port to patchright/httpx proxy dict."""
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        return None
    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"
    return ProxyConfig(
        server=server,
        username=parsed.username or "",
        password=parsed.password or "",
    )


# Module-level round-robin state; rebuilt when the pool string changes.
_pool_state: tuple[tuple[str, ...], itertools.cycle[str]] | None = None


def next_proxy() -> ProxyConfig | None:
    """Return the next proxy from the pool, or None when no proxy is configured."""
    global _pool_state

    from flight_alert_scraper.config import get_settings

    settings = get_settings()

    if settings.proxy_pool:
        urls = tuple(u.strip() for u in settings.proxy_pool.split(",") if u.strip())
        if urls:
            if _pool_state is None or _pool_state[0] != urls:
                _pool_state = (urls, itertools.cycle(urls))
            return parse_proxy(next(_pool_state[1]))

    if settings.proxy_url:
        return parse_proxy(settings.proxy_url)

    return None
