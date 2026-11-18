"""Runtime file helpers shared by the web process and the worker."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from django.utils import timezone

from ostium import paths


def read_usage() -> dict[str, Any]:
    path = paths.usage_path()
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError, ValueError:
        return {"updated_at": None, "stats_ok": False, "users": {}}
    if not isinstance(data, dict):
        return {"updated_at": None, "stats_ok": False, "users": {}}
    return data


def write_usage(data: dict[str, Any]) -> None:
    path = paths.usage_path()
    paths.ensure_parent(path)
    data = {**data, "updated_at": timezone.now().isoformat()}
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    paths.secure_file(temp)
    os.replace(temp, path)


def read_clash_secret() -> str:
    path = paths.clash_secret_path()
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def read_config_text() -> str:
    try:
        return paths.config_path().read_text(encoding="utf-8")
    except OSError:
        return ""


def tail_file(path: Path, *, max_bytes: int = 2 * 1024 * 1024) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
