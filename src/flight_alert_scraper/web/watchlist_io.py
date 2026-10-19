from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import yaml


def load_watchlist_raw(path: Path) -> list[dict[str, Any]]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("queries", []))


def save_watchlist(path: Path, queries: list[dict[str, Any]]) -> None:
    data: dict[str, Any] = {"queries": queries}
    text = yaml.safe_dump(
        data, default_flow_style=False, allow_unicode=True, sort_keys=False
    )
    if path.exists():
        shutil.copy2(path, path.with_suffix(".yaml.bak"))
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))
