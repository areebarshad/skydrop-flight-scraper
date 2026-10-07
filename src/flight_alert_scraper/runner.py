"""Orchestrates one query: scrape → rank → diff → notify → persist."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session

from flight_alert_scraper.db.repo import (
    alert_already_sent,
    finish_run,
    get_alert_state,
    log_alert,
    save_alert_state,
    start_run,
    upsert_watched_query,
)
from flight_alert_scraper.db.tables import AlertLog, AlertState
from flight_alert_scraper.engine.diffing import results_fingerprint
from flight_alert_scraper.engine.ranking import rank
from flight_alert_scraper.models.alert import AlertKind
from flight_alert_scraper.models.query import SearchQuery
from flight_alert_scraper.notifications.base import Notifier
from flight_alert_scraper.notifications.decide import decide
from flight_alert_scraper.notifications.render import render_html, render_subject, render_text
from flight_alert_scraper.scrapers.chain import ChainMetrics, ProviderChain

log = logging.getLogger(__name__)


def run_query(
    query: SearchQuery,
    chain: ProviderChain,
    session: Session,
    notifier: Notifier | None,
    dry_run: bool = False,
) -> None:
    upsert_watched_query(session, query)
    scrape_run = start_run(session, query.query_key)
    now = datetime.now(tz=timezone.utc)

    try:
        results, metrics = chain.search(query)
    except Exception as exc:
        log.error("Chain search failed: %s", exc)
        finish_run(session, scrape_run, None, None, "error", str(exc))
        return

    provider = metrics.serving_provider
    ranked = rank(results, query)

    alert_state = get_alert_state(session, query.query_key)
    decision = decide(ranked, alert_state, now)

    log.info(
        "Query %s: tier1=%d tier2=%d tier3=%d send=%s reason=%s",
        query.query_key,
        len(ranked.tier1),
        len(ranked.tier2),
        len(ranked.tier3),
        decision.should_send,
        decision.trigger_reason or decision.suppress_reason,
    )

    if decision.should_send and notifier is not None:
        subject = render_subject(decision)
        html_body = render_html(decision)
        text_body = render_text(decision)
        payload_hash = hashlib.sha256(
            (subject + html_body).encode()
        ).hexdigest()[:32]

        recipient = ""
        from flight_alert_scraper.config import get_settings
        settings = get_settings()
        recipient = settings.alert_recipient

        if dry_run:
            _write_preview(subject, html_body, text_body)
        elif not alert_already_sent(session, payload_hash, query.query_key):
            try:
                notifier.send(recipient, subject, html_body, text_body)
                log_alert(
                    session,
                    AlertLog(
                        query_key=query.query_key,
                        kind=decision.kind or AlertKind.IMMEDIATE,
                        trigger_reason=str(decision.trigger_reason or ""),
                        subject=subject,
                        payload_hash=payload_hash,
                        recipient=recipient,
                        sent_at=now,
                        delivery_ok=True,
                    ),
                )
            except Exception as exc:
                log.error("Email delivery failed: %s", exc)
                log_alert(
                    session,
                    AlertLog(
                        query_key=query.query_key,
                        kind=decision.kind or AlertKind.IMMEDIATE,
                        trigger_reason=str(decision.trigger_reason or ""),
                        subject=subject,
                        payload_hash=payload_hash,
                        recipient=recipient,
                        sent_at=now,
                        delivery_ok=False,
                        delivery_error=str(exc),
                    ),
                )

    new_fp = results_fingerprint(ranked)
    known_sigs = list({m.option.signature for m in ranked.tier1})
    best_t1 = ranked.tier1[0] if ranked.tier1 else None

    new_state = AlertState(
        query_key=query.query_key,
        results_fingerprint=new_fp,
        best_tier1_signature=best_t1.option.signature if best_t1 else None,
        best_tier1_price_usd=best_t1.option.price_usd if best_t1 else None,
        best_effective_cost_usd=best_t1.effective_cost_usd if best_t1 else None,
        known_tier1_signatures=json.dumps(known_sigs),
        last_immediate_sent_at=(
            now
            if decision.should_send and decision.kind == AlertKind.IMMEDIATE
            else (alert_state.last_immediate_sent_at if alert_state else None)
        ),
        last_digest_sent_at=(
            now
            if decision.should_send and decision.kind == AlertKind.DIGEST
            else (alert_state.last_digest_sent_at if alert_state else None)
        ),
        last_suppressed_reason=(
            str(decision.suppress_reason) if decision.suppress_reason else None
        ),
        updated_at=now,
    )
    save_alert_state(session, new_state)
    finish_run(session, scrape_run, ranked, provider, "ok")


def _write_preview(subject: str, html_body: str, text_body: str) -> None:
    preview_dir = Path("artifacts/preview")
    preview_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (preview_dir / f"{ts}_subject.txt").write_text(subject)
    (preview_dir / f"{ts}_email.html").write_text(html_body)
    (preview_dir / f"{ts}_email.txt").write_text(text_body)
    log.info("Preview written to %s", preview_dir / f"{ts}_email.html")
