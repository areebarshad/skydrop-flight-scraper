"""Command-line interface."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Flight route monitor and alert system.")
console = Console()


@app.command()
def check(
    dry_run: bool = typer.Option(False, "--dry-run", help="Render emails to artifacts/preview/ instead of sending."),
    watchlist: Optional[Path] = typer.Option(None, "--watchlist", help="Path to watchlist.yaml"),
) -> None:
    """Run a check of all watched routes and send alerts if anything changed."""
    from flight_alert_scraper import log as _log
    _log.configure()

    from flight_alert_scraper.config import Settings
    env_overrides: dict[str, object] = {}
    if watchlist:
        env_overrides["watchlist_path"] = watchlist
    if dry_run:
        env_overrides["dry_run"] = True
    settings = Settings(**env_overrides)

    from flight_alert_scraper.db.engine import get_session, migrate
    migrate(settings.db_path)

    from flight_alert_scraper.notifications.smtp import SmtpNotifier
    from flight_alert_scraper.scrapers.chain import ProviderChain
    from flight_alert_scraper.scrapers.google_browser import GoogleBrowserProvider
    from flight_alert_scraper.scrapers.google_http import GoogleHttpProvider
    from flight_alert_scraper.scrapers.serpapi import SerpApiProvider

    providers = [GoogleHttpProvider(), GoogleBrowserProvider()]
    if settings.serpapi_key:
        providers.append(SerpApiProvider(settings.serpapi_key))
    chain = ProviderChain(providers)

    notifier = None
    if not dry_run and settings.smtp_user and settings.smtp_app_password:
        notifier = SmtpNotifier(settings.smtp_user, settings.smtp_app_password)

    from flight_alert_scraper.runner import run_query

    queries = settings.load_queries()
    with get_session(settings.db_path) as session:
        for query in queries:
            console.print(f"[bold]Checking[/bold] {query.origin}→{query.destination} {query.depart_date}")
            run_query(query, chain, session, notifier, dry_run=dry_run)


@app.command("init-db")
def init_db(
    db: Path = typer.Option(Path("./flight_alerts.db"), "--db", help="Path to SQLite DB"),
) -> None:
    """Create or migrate the database schema."""
    from flight_alert_scraper.db.engine import migrate
    migrate(db)
    console.print(f"[green]Database initialized:[/green] {db}")


@app.command("history")
def history(
    query_key: Optional[str] = typer.Argument(None, help="Filter by query key"),
    db: Path = typer.Option(Path("./flight_alerts.db"), "--db"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """Show recent scrape run history."""
    from flight_alert_scraper.db.engine import get_session, migrate
    from flight_alert_scraper.db.repo import get_recent_runs
    from flight_alert_scraper.db.tables import WatchedQuery
    from sqlmodel import select

    migrate(db)
    with get_session(db) as session:
        if query_key:
            keys = [query_key]
        else:
            rows = session.exec(select(WatchedQuery)).all()
            keys = [r.query_key for r in rows]

        table = Table(title="Scrape History")
        table.add_column("Query Key")
        table.add_column("Started")
        table.add_column("Provider")
        table.add_column("Status")
        table.add_column("T1")
        table.add_column("T2")
        table.add_column("Suppressed")

        for key in keys:
            runs = get_recent_runs(session, key, limit=limit)
            from flight_alert_scraper.db.repo import get_alert_state
            state = get_alert_state(session, key)
            suppressed = state.last_suppressed_reason if state else ""
            for run in runs:
                table.add_row(
                    key[:8],
                    str(run.started_at)[:19],
                    run.provider or "—",
                    run.status,
                    str(run.tier1_count),
                    str(run.tier2_count),
                    suppressed or "",
                )
        console.print(table)


@app.command("test-email")
def test_email(
    dry_run: bool = typer.Option(True, "--dry-run/--send"),
    db: Path = typer.Option(Path("./flight_alerts.db"), "--db"),
) -> None:
    """Render a test email with synthetic data."""
    from datetime import date, datetime, timezone
    from decimal import Decimal

    from flight_alert_scraper.models.flight import BookingLinks, FlightOption, Leg
    from flight_alert_scraper.models.query import CabinClass, Constraints, SearchQuery
    from flight_alert_scraper.models.result import MatchLabel, RankedResults, Tier, TieredMatch
    from flight_alert_scraper.models.alert import AlertDecision, AlertKind, TriggerReason
    from flight_alert_scraper.notifications.render import render_html, render_subject, render_text

    now = datetime.now(tz=timezone.utc)
    leg = Leg(
        carrier="Pakistan International Airlines",
        carrier_code="PK",
        flight_number="785",
        origin="IAD",
        destination="KHI",
        depart_at=now,
        arrive_at=datetime.fromtimestamp(now.timestamp() + 21 * 3600, tz=timezone.utc),
        duration_minutes=1260,
    )
    links = BookingLinks(
        google_search="https://www.google.com/travel/flights",
        kayak_search="https://www.kayak.com/flights/IAD-KHI",
    )
    option = FlightOption(
        legs=[leg],
        layovers=[],
        price_usd=Decimal("1150.00"),
        total_duration_minutes=1260,
        links=links,
        source="fixture",
        scraped_at=now,
    )
    constraints = Constraints(max_price_usd=Decimal("1200"), max_duration_minutes=1320)
    query = SearchQuery(
        origin="IAD",
        destination="KHI",
        depart_date=date(2026, 12, 1),
        cabin=CabinClass.ECONOMY,
        adults=1,
        constraints=constraints,
    )
    match = TieredMatch(
        option=option,
        tier=Tier.DIRECT_MATCH,
        labels=[MatchLabel.DIRECT],
        effective_cost_usd=Decimal("1570.00"),
        price_delta_usd=Decimal("-50.00"),
        duration_delta_minutes=-60,
        tradeoff_note="$1,150, 21h — meets all constraints",
    )
    ranked = RankedResults(
        query=query,
        tier1=[match],
        tier2=[],
        tier3=[],
        total_candidates=8,
        filtered_out=0,
    )
    decision = AlertDecision(
        should_send=True,
        kind=AlertKind.IMMEDIATE,
        trigger_reason=TriggerReason.NEW_TIER1,
        ranked=ranked,
    )

    subject = render_subject(decision)
    html_body = render_html(decision)
    text_body = render_text(decision)

    if dry_run:
        from pathlib import Path
        preview_dir = Path("artifacts/preview")
        preview_dir.mkdir(parents=True, exist_ok=True)
        ts = now.strftime("%Y%m%dT%H%M%SZ")
        (preview_dir / f"{ts}_subject.txt").write_text(subject)
        (preview_dir / f"{ts}_email.html").write_text(html_body)
        (preview_dir / f"{ts}_email.txt").write_text(text_body)
        console.print(f"[green]Preview written to[/green] artifacts/preview/{ts}_email.html")
        console.print(f"Subject: {subject}")
    else:
        from flight_alert_scraper.config import get_settings
        from flight_alert_scraper.notifications.smtp import SmtpNotifier
        settings = get_settings()
        notifier = SmtpNotifier(settings.smtp_user, settings.smtp_app_password)
        notifier.send(settings.alert_recipient, subject, html_body, text_body)
        console.print(f"[green]Sent to {settings.alert_recipient}[/green]")


@app.command("rank")
def rank_cmd(
    from_fixture: Optional[Path] = typer.Option(None, "--from-fixture", help="JSON fixture file"),
) -> None:
    """Rank flights from a fixture file and print the three tiers."""
    import json
    from flight_alert_scraper.engine.ranking import rank
    from flight_alert_scraper.models.flight import FlightOption
    from flight_alert_scraper.models.query import CabinClass, Constraints, SearchQuery
    from datetime import date
    from decimal import Decimal

    if from_fixture is None:
        console.print("[red]Provide --from-fixture path[/red]")
        raise typer.Exit(1)

    data = json.loads(from_fixture.read_text())
    options = [FlightOption.model_validate(o) for o in data["options"]]
    q_data = data["query"]
    constraints = Constraints(**q_data.pop("constraints"))
    q_data["cabin"] = CabinClass(q_data.get("cabin", "economy"))
    q_data["depart_date"] = date.fromisoformat(q_data["depart_date"])
    if q_data.get("return_date"):
        q_data["return_date"] = date.fromisoformat(q_data["return_date"])
    query = SearchQuery(**q_data, constraints=constraints)
    ranked = rank(options, query)

    def _show_tier(title: str, matches):
        if not matches:
            return
        t = Table(title=title)
        t.add_column("Price")
        t.add_column("Duration")
        t.add_column("Stops")
        t.add_column("Labels")
        t.add_column("Note")
        for m in matches:
            h, mn = divmod(m.option.total_duration_minutes, 60)
            t.add_row(
                f"${m.option.price_usd:.0f}",
                f"{h}h {mn}m",
                str(m.option.stops),
                ", ".join(m.labels),
                m.tradeoff_note[:60],
            )
        console.print(t)

    _show_tier("Tier 1 — Direct Matches", ranked.tier1)
    _show_tier("Tier 2 — Near Misses", ranked.tier2)
    _show_tier("Tier 3 — Baseline", ranked.tier3)
    console.print(
        f"[dim]total={ranked.total_candidates} filtered_out={ranked.filtered_out}[/dim]"
    )
