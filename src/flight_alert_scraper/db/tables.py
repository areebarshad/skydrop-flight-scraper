from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlmodel import Field, SQLModel, UniqueConstraint


class WatchedQuery(SQLModel, table=True):
    __tablename__ = "watched_query"

    query_key: str = Field(primary_key=True)
    origin: str
    destination: str
    depart_date: str
    return_date: str | None = None
    cabin: str
    adults: int
    constraints_json: str
    created_at: datetime
    last_checked_at: datetime | None = None
    active: bool = True


class ScrapeRun(SQLModel, table=True):
    __tablename__ = "scrape_run"

    id: int | None = Field(default=None, primary_key=True)
    query_key: str = Field(foreign_key="watched_query.query_key", index=True)
    started_at: datetime
    finished_at: datetime | None = None
    provider: str | None = None
    status: str = "ok"
    candidates_found: int = 0
    tier1_count: int = 0
    tier2_count: int = 0
    error_message: str | None = None


class FlightSnapshot(SQLModel, table=True):
    __tablename__ = "flight_snapshot"

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="scrape_run.id")
    query_key: str = Field(index=True)
    signature: str = Field(index=True)
    price_usd: Decimal
    total_duration_minutes: int
    stops: int
    carriers: str
    tier: int
    labels: str
    effective_cost_usd: Decimal
    option_json: str
    observed_at: datetime = Field(index=True)

    __table_args__ = (UniqueConstraint("run_id", "signature"),)


class AlertState(SQLModel, table=True):
    __tablename__ = "alert_state"

    query_key: str = Field(primary_key=True)
    results_fingerprint: str | None = None
    best_tier1_signature: str | None = None
    best_tier1_price_usd: Decimal | None = None
    best_effective_cost_usd: Decimal | None = None
    known_tier1_signatures: str = "[]"
    last_immediate_sent_at: datetime | None = None
    last_digest_sent_at: datetime | None = None
    last_suppressed_reason: str | None = None
    updated_at: datetime


class AlertLog(SQLModel, table=True):
    __tablename__ = "alert_log"

    id: int | None = Field(default=None, primary_key=True)
    query_key: str = Field(index=True)
    kind: str
    trigger_reason: str
    subject: str
    payload_hash: str
    recipient: str
    sent_at: datetime = Field(index=True)
    delivery_ok: bool
    delivery_error: str | None = None


class UserSetting(SQLModel, table=True):
    __tablename__ = "user_setting"

    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime
