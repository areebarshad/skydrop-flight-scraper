from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

_engine = None


def get_engine(db_path: Path | str = "./flight_alerts.db"):
    global _engine
    if _engine is None:
        url = f"sqlite:///{db_path}"
        _engine = create_engine(url, connect_args={"check_same_thread": False})
    return _engine


def migrate(db_path: Path | str = "./flight_alerts.db") -> None:
    from flight_alert_scraper.db import tables as _  # noqa: F401 — register table metadata

    eng = get_engine(db_path)
    SQLModel.metadata.create_all(eng)


def get_session(db_path: Path | str = "./flight_alerts.db") -> Session:
    return Session(get_engine(db_path))
