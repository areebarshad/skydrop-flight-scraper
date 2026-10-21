from __future__ import annotations

import os
import shutil
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            result[key.strip()] = value.strip()
    return result


def save_env(path: Path, updates: dict[str, str]) -> None:
    lines: list[str] = []
    seen_keys: set[str] = set()

    if path.exists():
        shutil.copy2(path, Path(str(path) + ".bak"))
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.partition("=")[0].strip()
                if key in updates:
                    lines.append(f"{key}={updates[key]}")
                    seen_keys.add(key)
                    continue
            lines.append(line)

    for key, value in updates.items():
        if key not in seen_keys:
            lines.append(f"{key}={value}")

    tmp = Path(str(path) + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))
