from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from flight_alert_scraper.config import Settings
from flight_alert_scraper.db.engine import get_session
from flight_alert_scraper.db.repo import (
    get_alert_state,
    get_latest_run,
    get_price_history,
    get_recent_alerts,
    get_recent_runs,
    get_snapshots_for_run,
    list_watched_queries,
)
from flight_alert_scraper.db.tables import WatchedQuery
from flight_alert_scraper.web import jobs as _jobs
from flight_alert_scraper.web.presenters import (
    build_price_svg,
    fmt_relative_time,
    snapshot_to_card,
)
from flight_alert_scraper.web.watchlist_io import load_watchlist_raw, save_watchlist

log = logging.getLogger(__name__)

_HERE = Path(__file__).parent


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="skydrop", docs_url=None, redoc_url=None)

    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")
    templates = Jinja2Templates(directory=str(_HERE / "templates"))

    def _all_routes() -> list[WatchedQuery]:
        with get_session(settings.db_path) as s:
            return list_watched_queries(s)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.get("/", response_class=RedirectResponse)
    async def root() -> RedirectResponse:
        routes = _all_routes()
        if not routes:
            raise HTTPException(404, "No watched routes found")
        return RedirectResponse(f"/routes/{routes[0].query_key}", status_code=302)

    @app.get("/routes/{query_key}", response_class=HTMLResponse)
    async def dashboard(query_key: str, request: Request) -> HTMLResponse:
        with get_session(settings.db_path) as session:
            wq = session.get(WatchedQuery, query_key)
            if wq is None:
                raise HTTPException(404, f"Route {query_key!r} not found")
            all_routes = list_watched_queries(session)
            latest_run = get_latest_run(session, query_key)
            alert_state = get_alert_state(session, query_key)
            snapshots = (
                get_snapshots_for_run(session, latest_run.id)
                if latest_run and latest_run.id
                else []
            )
            price_history = get_price_history(session, query_key)
            recent_runs = get_recent_runs(session, query_key, limit=20)
            recent_alerts = get_recent_alerts(session, query_key)

        constraints: dict[str, Any] = json.loads(wq.constraints_json)
        budget = Decimal(str(constraints.get("max_price_usd", "9999")))
        max_dur_min: int | None = constraints.get("max_duration_minutes")

        tier1_cards = [snapshot_to_card(s) for s in snapshots if s.tier == 1]
        tier2_cards = [snapshot_to_card(s) for s in snapshots if s.tier == 2]
        tier3_cards = [snapshot_to_card(s) for s in snapshots if s.tier == 3]
        hero: dict[str, Any] | None = next(
            iter(tier1_cards or tier2_cards or tier3_cards), None
        )
        price_svg = (
            build_price_svg(price_history, budget) if len(price_history) >= 2 else None
        )

        constraint_line_parts = [f"budget ${budget:,.0f}"]
        if max_dur_min:
            h, m = divmod(max_dur_min, 60)
            constraint_line_parts.append(f"limit {h}h" + (f" {m}m" if m else ""))
        constraint_line = " · ".join(constraint_line_parts)

        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "query_key": query_key,
                "wq": wq,
                "all_routes": all_routes,
                "latest_run": latest_run,
                "alert_state": alert_state,
                "hero": hero,
                "tier1_cards": tier1_cards,
                "tier2_cards": tier2_cards,
                "tier3_cards": tier3_cards,
                "price_svg": price_svg,
                "price_history_count": len(price_history),
                "recent_runs": recent_runs,
                "recent_alerts": recent_alerts,
                "constraints": constraints,
                "constraint_line": constraint_line,
                "last_checked_str": fmt_relative_time(wq.last_checked_at),
            },
        )

    @app.post("/routes/{query_key}/check", response_class=HTMLResponse)
    async def start_check(query_key: str, request: Request) -> HTMLResponse:
        with get_session(settings.db_path) as session:
            wq = session.get(WatchedQuery, query_key)
            if wq is None:
                raise HTTPException(404)
        job_id = _jobs.start_check(query_key)
        job = _jobs.get_job(job_id)
        return templates.TemplateResponse(
            request,
            "partials/job_status.html",
            {
                "job_id": job_id,
                "job": job,
                "query_key": query_key,
            },
        )

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    async def poll_job(job_id: str, request: Request) -> HTMLResponse:
        job = _jobs.get_job(job_id)
        if job is None:
            return HTMLResponse('<span class="job-msg">Job not found</span>')
        if job["state"] in ("done", "error"):
            resp = HTMLResponse(
                f'<span class="job-msg job-{job["state"]}">{job["message"]}</span>'
            )
            resp.headers["HX-Redirect"] = f"/routes/{job['query_key']}"
            return resp
        return templates.TemplateResponse(
            request,
            "partials/job_status.html",
            {
                "job_id": job_id,
                "job": job,
                "query_key": job["query_key"],
            },
        )

    @app.get("/routes/{query_key}/email-preview", response_class=HTMLResponse)
    async def email_preview(query_key: str, request: Request) -> HTMLResponse:
        with get_session(settings.db_path) as session:
            wq = session.get(WatchedQuery, query_key)
            if wq is None:
                raise HTTPException(404)
            latest_run = get_latest_run(session, query_key)
            if latest_run is None or latest_run.id is None:
                return templates.TemplateResponse(
                    request,
                    "partials/no_preview.html",
                    {"query_key": query_key},
                )
            snapshots = get_snapshots_for_run(session, latest_run.id)
            alert_state = get_alert_state(session, query_key)

        import datetime as dt_mod

        from flight_alert_scraper.engine.ranking import rank
        from flight_alert_scraper.models.flight import FlightOption
        from flight_alert_scraper.models.query import (
            CabinClass,
            Constraints,
            SearchQuery,
        )
        from flight_alert_scraper.notifications.decide import decide
        from flight_alert_scraper.notifications.render import (
            render_html,
            render_subject,
        )

        options: list[FlightOption] = []
        for snap in snapshots:
            try:
                options.append(FlightOption.model_validate_json(snap.option_json))
            except Exception:
                pass

        if not options:
            return templates.TemplateResponse(
                request,
                "partials/no_preview.html",
                {"query_key": query_key},
            )

        try:
            c_data: dict[str, Any] = json.loads(wq.constraints_json)
            constraints_obj = Constraints(**c_data)
            query = SearchQuery(
                origin=wq.origin,
                destination=wq.destination,
                depart_date=dt_mod.date.fromisoformat(wq.depart_date),
                return_date=(
                    dt_mod.date.fromisoformat(wq.return_date)
                    if wq.return_date
                    else None
                ),
                cabin=CabinClass(wq.cabin),
                adults=wq.adults,
                constraints=constraints_obj,
            )
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc

        now = datetime.now(tz=dt_mod.UTC)
        ranked = rank(options, query)
        decision = decide(ranked, alert_state, now)
        subject = render_subject(decision)
        html_body = render_html(decision)

        return templates.TemplateResponse(
            request,
            "email_preview.html",
            {
                "query_key": query_key,
                "subject": subject,
                "email_body": html_body,
                "all_routes": _all_routes(),
            },
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_get(request: Request) -> HTMLResponse:
        queries = load_watchlist_raw(settings.watchlist_path)
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "queries": queries,
                "errors": [],
                "success": False,
                "all_routes": _all_routes(),
                "query_key": None,
            },
        )

    @app.post("/settings", response_class=HTMLResponse)
    async def settings_post(request: Request) -> HTMLResponse:
        import datetime as dt_mod

        from pydantic import ValidationError

        from flight_alert_scraper.models.query import (
            CabinClass,
            Constraints,
            SearchQuery,
        )

        form = await request.form()
        num_raw = form.get("num_queries", "0")
        try:
            num = int(str(num_raw))
        except ValueError:
            num = 0

        errors: list[str] = []
        new_queries: list[dict[str, Any]] = []

        for i in range(num):

            def _f(key: str, idx: int = i) -> str:
                v = form.get(f"{key}_{idx}")
                return str(v).strip() if v else ""

            try:
                max_price_raw = _f("max_price_usd")
                max_dur_raw = _f("max_duration_minutes")
                max_stops_raw = _f("max_stops")
                constraints_obj = Constraints(
                    max_price_usd=(
                        Decimal(max_price_raw) if max_price_raw else Decimal("9999")
                    ),
                    max_duration_minutes=int(max_dur_raw) if max_dur_raw else None,
                    max_stops=int(max_stops_raw) if max_stops_raw else None,
                    value_deal_discount=Decimal(_f("value_deal_discount") or "0.20"),
                    value_deal_duration_buffer_minutes=int(
                        _f("value_deal_duration_buffer_minutes") or "180"
                    ),
                    time_saver_price_overage=Decimal(
                        _f("time_saver_price_overage") or "0.10"
                    ),
                    hourly_time_penalty_usd=Decimal(
                        _f("hourly_time_penalty_usd") or "20.00"
                    ),
                )
                ret_raw = _f("return_date")
                query = SearchQuery(
                    origin=_f("origin"),
                    destination=_f("destination"),
                    depart_date=dt_mod.date.fromisoformat(_f("depart_date")),
                    return_date=(
                        dt_mod.date.fromisoformat(ret_raw) if ret_raw else None
                    ),
                    cabin=CabinClass(_f("cabin") or "economy"),
                    adults=int(_f("adults") or "1"),
                    constraints=constraints_obj,
                )
                old_key_raw = _f("old_query_key")
                row: dict[str, Any] = {
                    "origin": query.origin,
                    "destination": query.destination,
                    "depart_date": query.depart_date.isoformat(),
                    "cabin": str(query.cabin),
                    "adults": query.adults,
                    "constraints": {
                        "max_price_usd": str(constraints_obj.max_price_usd),
                        "max_duration_minutes": constraints_obj.max_duration_minutes,
                        "max_stops": constraints_obj.max_stops,
                        "value_deal_discount": str(constraints_obj.value_deal_discount),
                        "value_deal_duration_buffer_minutes": (
                            constraints_obj.value_deal_duration_buffer_minutes
                        ),
                        "time_saver_price_overage": str(
                            constraints_obj.time_saver_price_overage
                        ),
                        "hourly_time_penalty_usd": str(
                            constraints_obj.hourly_time_penalty_usd
                        ),
                    },
                }
                if ret_raw and query.return_date:
                    row["return_date"] = query.return_date.isoformat()
                if old_key_raw and old_key_raw != query.query_key:
                    errors.append(
                        f"Row {i + 1}: changing origin/destination/dates/cabin/pax "
                        f"creates a new route key "
                        f"({old_key_raw[:8]}→{query.query_key[:8]}). "
                        f"Old history will be orphaned."
                    )
                new_queries.append(row)
            except (ValidationError, ValueError, InvalidOperation) as exc:
                errors.append(f"Row {i + 1}: {exc}")

        if not errors:
            save_watchlist(settings.watchlist_path, new_queries)

        queries = load_watchlist_raw(settings.watchlist_path)
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "queries": queries,
                "errors": errors,
                "success": not errors,
                "all_routes": _all_routes(),
                "query_key": None,
            },
        )

    return app
