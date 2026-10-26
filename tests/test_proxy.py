"""Tests for proxy parsing and round-robin rotation."""
from __future__ import annotations

from flight_alert_scraper.scrapers.proxy import parse_proxy


def test_parse_full_url() -> None:
    cfg = parse_proxy("http://user:pass@proxy.example.com:8080")
    assert cfg is not None
    assert cfg["server"] == "http://proxy.example.com:8080"
    assert cfg["username"] == "user"
    assert cfg["password"] == "pass"


def test_parse_no_port() -> None:
    cfg = parse_proxy("socks5://u:p@proxy.example.com")
    assert cfg is not None
    assert cfg["server"] == "socks5://proxy.example.com"


def test_parse_no_credentials() -> None:
    cfg = parse_proxy("http://proxy.example.com:3128")
    assert cfg is not None
    assert cfg["username"] == ""
    assert cfg["password"] == ""


def test_parse_empty_returns_none() -> None:
    assert parse_proxy("") is None


def test_parse_invalid_returns_none() -> None:
    assert parse_proxy("not-a-url") is None


def test_next_proxy_returns_none_when_not_configured(monkeypatch) -> None:
    import flight_alert_scraper.config as cfg_mod
    import flight_alert_scraper.scrapers.proxy as proxy_mod

    monkeypatch.setattr(cfg_mod, "_settings", None)

    monkeypatch.setenv("PROXY_URL", "")
    monkeypatch.setenv("PROXY_POOL", "")

    proxy_mod._pool_state = None

    from flight_alert_scraper.config import reset_settings
    reset_settings()

    from flight_alert_scraper.scrapers.proxy import next_proxy
    result = next_proxy()
    assert result is None


def test_next_proxy_roundrobin(monkeypatch) -> None:
    import flight_alert_scraper.scrapers.proxy as proxy_mod
    from flight_alert_scraper.config import Settings

    proxy_mod._pool_state = None
    fake_settings = Settings(
        proxy_pool="http://a:x@h1:1,http://b:y@h2:2",
    )
    monkeypatch.setattr(
        "flight_alert_scraper.config.get_settings", lambda: fake_settings
    )

    from flight_alert_scraper.scrapers.proxy import next_proxy

    first = next_proxy()
    second = next_proxy()
    third = next_proxy()

    assert first is not None
    assert second is not None
    assert first["server"] != second["server"]
    assert third["server"] == first["server"]
