from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from flight_alert_scraper.config import Settings
from flight_alert_scraper.db.engine import get_session
from flight_alert_scraper.db.repo import (
    deactivate_watched_query,
    get_alert_state,
    get_cheapest_carrier_by_run,
    get_latest_run,
    get_price_history,
    get_recent_alerts,
    get_recent_runs,
    get_snapshots_for_run,
    set_user_setting,
)
from flight_alert_scraper.db.tables import ScrapeRun, WatchedQuery
from flight_alert_scraper.models.query import CabinClass
from flight_alert_scraper.web import jobs as _jobs
from flight_alert_scraper.web.env_io import load_env, save_env
from flight_alert_scraper.web.forms import (
    query_key_for_row,
    row_from_form,
    validate_email,
)
from flight_alert_scraper.web.presenters import (
    build_price_svg,
    fmt_relative_time,
    snapshot_to_card,
)
from flight_alert_scraper.web.watchlist_io import load_watchlist_raw, save_watchlist

log = logging.getLogger(__name__)

_HERE = Path(__file__).parent
_ENV_PATH = Path(".env")


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="skydrop", docs_url=None, redoc_url=None)

    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")
    templates = Jinja2Templates(directory=str(_HERE / "templates"))

    def _log_rows() -> list[dict[str, Any]]:
        raw_rows = load_watchlist_raw(settings.watchlist_path)
        rows: list[dict[str, Any]] = []
        with get_session(settings.db_path) as session:
            for raw in raw_rows:
                try:
                    key = query_key_for_row(raw)
                except Exception:
                    continue
                wq = session.get(WatchedQuery, key)
                latest_run = get_latest_run(session, key) if wq else None
                snapshots = (
                    get_snapshots_for_run(session, latest_run.id)
                    if latest_run and latest_run.id
                    else []
                )
                cards = [snapshot_to_card(s) for s in snapshots]
                best_price = min((c["price_raw"] for c in cards), default=None)
                tier1_count = sum(1 for c in cards if c["tier"] == 1)
                rows.append(
                    {
                        "query_key": key,
                        "origin": raw["origin"],
                        "destination": raw["destination"],
                        "depart_date": raw.get("depart_date", ""),
                        "return_date": raw.get("return_date"),
                        "cabin": raw.get("cabin", "economy"),
                        "adults": raw.get("adults", 1),
                        "best_price": (
                            f"${best_price:,.0f}" if best_price is not None else None
                        ),
                        "tier1_count": tier1_count,
                        "last_checked_str": fmt_relative_time(
                            wq.last_checked_at if wq else None
                        ),
                    }
                )
        return rows

    def _wq_from_watchlist(query_key: str) -> WatchedQuery | None:
        raw_rows = load_watchlist_raw(settings.watchlist_path)
        for r in raw_rows:
            try:
                if query_key_for_row(r) == query_key:
                    return WatchedQuery(
                        query_key=query_key,
                        origin=r["origin"],
                        destination=r["destination"],
                        depart_date=r.get("depart_date", ""),
                        return_date=r.get("return_date"),
                        cabin=str(CabinClass(r.get("cabin", "economy"))),
                        adults=r.get("adults", 1),
                        constraints_json=json.dumps(r.get("constraints", {})),
                        created_at=datetime.now(tz=UTC),
                        last_checked_at=None,
                    )
            except Exception:
                continue
        return None

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.get("/", response_class=RedirectResponse)
    async def root() -> RedirectResponse:
        return RedirectResponse("/logs", status_code=302)

    # ── Logs tab ──────────────────────────────────────────────

    @app.get("/logs", response_class=HTMLResponse)
    async def logs_list(request: Request) -> HTMLResponse:
        env = load_env(_ENV_PATH)
        return templates.TemplateResponse(
            request,
            "logs.html",
            {
                "rows": _log_rows(),
                "active_tab": "logs",
                "env": env,
                "settings_error": None,
                "settings_saved": False,
            },
        )

    @app.get("/logs/new", response_class=HTMLResponse)
    async def log_new_get(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "log_form.html",
            {
                "mode": "add",
                "action": "/logs/new",
                "row": None,
                "errors": [],
                "active_tab": "logs",
            },
        )

    @app.post("/logs/new", response_class=HTMLResponse, response_model=None)
    async def log_new_post(request: Request) -> HTMLResponse | RedirectResponse:
        form = await request.form()
        try:
            row = row_from_form(form)
        except (ValidationError, ValueError, InvalidOperation) as exc:
            return templates.TemplateResponse(
                request,
                "log_form.html",
                {
                    "mode": "add",
                    "action": "/logs/new",
                    "row": None,
                    "errors": [str(exc)],
                    "active_tab": "logs",
                },
            )
        existing = load_watchlist_raw(settings.watchlist_path)
        existing.append(row)
        save_watchlist(settings.watchlist_path, existing)
        return RedirectResponse("/logs", status_code=303)

    @app.post("/logs/settings", response_class=HTMLResponse, response_model=None)
    async def logs_settings_post(request: Request) -> HTMLResponse | RedirectResponse:
        form = await request.form()
        smtp_user = str(form.get("smtp_user", "")).strip()
        smtp_app_password = str(form.get("smtp_app_password", "")).strip()
        alert_recipient = str(form.get("alert_recipient", "")).strip()
        serpapi_key = str(form.get("serpapi_key", "")).strip()

        if alert_recipient and not validate_email(alert_recipient):
            env = load_env(_ENV_PATH)
            return templates.TemplateResponse(
                request,
                "logs.html",
                {
                    "rows": _log_rows(),
                    "active_tab": "logs",
                    "env": env,
                    "settings_error": "Enter a valid email address.",
                    "settings_saved": False,
                },
            )

        updates: dict[str, str] = {"SERPAPI_KEY": serpapi_key}
        if smtp_user:
            updates["SMTP_USER"] = smtp_user
        if smtp_app_password:
            updates["SMTP_APP_PASSWORD"] = smtp_app_password
        if alert_recipient:
            updates["ALERT_RECIPIENT"] = alert_recipient

        save_env(_ENV_PATH, updates)

        from flight_alert_scraper.config import reset_settings
        reset_settings()

        if alert_recipient:
            with get_session(settings.db_path) as session:
                set_user_setting(session, "alert_recipient", alert_recipient)

        return RedirectResponse("/logs#settings", status_code=303)

    @app.get("/logs/{query_key}/edit", response_class=HTMLResponse)
    async def log_edit_get(query_key: str, request: Request) -> HTMLResponse:
        rows = load_watchlist_raw(settings.watchlist_path)
        matched: dict[str, Any] | None = None
        for r in rows:
            try:
                if query_key_for_row(r) == query_key:
                    matched = r
                    break
            except Exception:
                continue
        if matched is None:
            raise HTTPException(404, f"Flight {query_key!r} not found in watchlist")
        return templates.TemplateResponse(
            request,
            "log_form.html",
            {
                "mode": "edit",
                "action": f"/logs/{query_key}/edit",
                "row": matched,
                "errors": [],
                "active_tab": "logs",
            },
        )

    @app.post(
        "/logs/{query_key}/edit", response_class=HTMLResponse, response_model=None
    )
    async def log_edit_post(
        query_key: str, request: Request
    ) -> HTMLResponse | RedirectResponse:
        form = await request.form()
        try:
            new_row = row_from_form(form)
        except (ValidationError, ValueError, InvalidOperation) as exc:
            rows = load_watchlist_raw(settings.watchlist_path)
            old_row = next(
                (r for r in rows if query_key_for_row(r) == query_key), None
            )
            return templates.TemplateResponse(
                request,
                "log_form.html",
                {
                    "mode": "edit",
                    "action": f"/logs/{query_key}/edit",
                    "row": old_row,
                    "errors": [str(exc)],
                    "active_tab": "logs",
                },
            )
        new_key = query_key_for_row(new_row)
        rows = load_watchlist_raw(settings.watchlist_path)
        updated = False
        warnings: list[str] = []
        new_rows: list[dict[str, Any]] = []
        for r in rows:
            try:
                rk = query_key_for_row(r)
            except Exception:
                new_rows.append(r)
                continue
            if rk == query_key:
                if new_key != query_key:
                    warnings.append(
                        f"Changing origin/destination/dates/cabin/pax creates a new "
                        f"key ({query_key[:8]}→{new_key[:8]}). Old history is orphaned."
                    )
                new_rows.append(new_row)
                updated = True
            else:
                new_rows.append(r)
        if not updated:
            new_rows.append(new_row)
        save_watchlist(settings.watchlist_path, new_rows)
        if warnings:
            return templates.TemplateResponse(
                request,
                "log_form.html",
                {
                    "mode": "edit",
                    "action": f"/logs/{new_key}/edit",
                    "row": new_row,
                    "errors": warnings,
                    "active_tab": "logs",
                },
            )
        return RedirectResponse("/logs", status_code=303)

    @app.post("/logs/{query_key}/delete", response_class=HTMLResponse)
    async def log_delete(query_key: str) -> RedirectResponse:
        rows = load_watchlist_raw(settings.watchlist_path)
        new_rows = []
        for r in rows:
            try:
                if query_key_for_row(r) != query_key:
                    new_rows.append(r)
            except Exception:
                new_rows.append(r)
        save_watchlist(settings.watchlist_path, new_rows)
        with get_session(settings.db_path) as session:
            deactivate_watched_query(session, query_key)
        return RedirectResponse("/logs", status_code=303)

    @app.get("/logs/{query_key}/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail(query_key: str, run_id: int, request: Request) -> HTMLResponse:
        with get_session(settings.db_path) as session:
            run = session.get(ScrapeRun, run_id)
            if run is None or run.query_key != query_key:
                raise HTTPException(404)
            snapshots = get_snapshots_for_run(session, run_id)
            wq: WatchedQuery | None = session.get(WatchedQuery, query_key)

        if wq is None:
            wq = _wq_from_watchlist(query_key)

        cards = [snapshot_to_card(s) for s in snapshots]
        ranked_cards = sorted(cards, key=lambda c: c["price_raw"])

        return templates.TemplateResponse(
            request,
            "run_detail.html",
            {
                "query_key": query_key,
                "run": run,
                "ranked_cards": ranked_cards,
                "wq": wq,
                "active_tab": "logs",
            },
        )

    @app.get("/logs/{query_key}", response_class=HTMLResponse)
    async def log_detail(
        query_key: str, request: Request, ran: str | None = None
    ) -> HTMLResponse:
        with get_session(settings.db_path) as session:
            wq: WatchedQuery | None = session.get(WatchedQuery, query_key)

            if wq is None:
                wq = _wq_from_watchlist(query_key)
                if wq is None:
                    raise HTTPException(404, f"Route {query_key!r} not found")

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
            run_ids = [r.id for r in recent_runs if r.id is not None]
            cheapest_by_run = get_cheapest_carrier_by_run(session, run_ids)

        job_id: str | None = None
        if ran is None:
            job_id = _jobs.start_check(query_key)

        constraints: dict[str, Any] = json.loads(wq.constraints_json)
        budget = Decimal(str(constraints.get("max_price_usd", "9999")))
        max_dur_min: int | None = constraints.get("max_duration_minutes")

        all_cards = [snapshot_to_card(s) for s in snapshots]
        ranked_cards = sorted(all_cards, key=lambda c: c["price_raw"])
        hero: dict[str, Any] | None = ranked_cards[0] if ranked_cards else None
        tier1_count = sum(1 for c in all_cards if c["tier"] == 1)

        price_svg = (
            build_price_svg(price_history, budget) if len(price_history) >= 1 else None
        )

        constraint_line_parts = [f"budget ${budget:,.0f}"]
        if max_dur_min:
            h, m = divmod(max_dur_min, 60)
            constraint_line_parts.append(f"limit {h}h" + (f" {m}m" if m else ""))
        constraint_line = " · ".join(constraint_line_parts)

        first_run_error: str | None = None
        if recent_runs and recent_runs[0].error_message:
            first_run_error = recent_runs[0].error_message

        return templates.TemplateResponse(
            request,
            "log_detail.html",
            {
                "query_key": query_key,
                "wq": wq,
                "latest_run": latest_run,
                "alert_state": alert_state,
                "hero": hero,
                "ranked_cards": ranked_cards,
                "tier1_count": tier1_count,
                "price_svg": price_svg,
                "price_history_count": len(price_history),
                "recent_runs": recent_runs,
                "recent_alerts": recent_alerts,
                "constraints": constraints,
                "constraint_line": constraint_line,
                "last_checked_str": fmt_relative_time(wq.last_checked_at),
                "active_tab": "logs",
                "job_id": job_id,
                "first_run_error": first_run_error,
                "cheapest_by_run": cheapest_by_run,
            },
        )

    @app.post("/logs/{query_key}/check", response_class=HTMLResponse)
    async def start_check(query_key: str, request: Request) -> HTMLResponse:
        with get_session(settings.db_path) as session:
            wq: WatchedQuery | None = session.get(WatchedQuery, query_key)
        if wq is None:
            wq = _wq_from_watchlist(query_key)
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

    @app.get("/logs/{query_key}/email-preview", response_class=HTMLResponse)
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
                "active_tab": "logs",
            },
        )

    # ── Jobs ──────────────────────────────────────────────────

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    async def poll_job(job_id: str, request: Request) -> HTMLResponse:
        job = _jobs.get_job(job_id)
        if job is None:
            return HTMLResponse('<span class="job-msg">Job not found</span>')
        if job["state"] in ("done", "error"):
            resp = HTMLResponse(
                f'<span class="job-msg job-{job["state"]}">{job["message"]}</span>'
            )
            resp.headers["HX-Redirect"] = f"/logs/{job['query_key']}?ran=1"
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

    return app
