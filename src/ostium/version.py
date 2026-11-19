"""Version and build information."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_FALLBACK = "0.2.13"


def _read_version_file() -> str | None:
    for candidate in (
        Path(__file__).resolve().parents[2] / "VERSION",
        Path(os.environ.get("OSTIUM_ROOT", "/opt/ostium")) / "VERSION",
    ):
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return None


def get_version() -> str:
    try:
        return version("ostium-ctl")
    except PackageNotFoundError:
        return _read_version_file() or _FALLBACK


__version__ = get_version()
BUILD_COMMIT = os.environ.get("OSTIUM_BUILD_COMMIT", "dev")
BUILD_DATE = os.environ.get("OSTIUM_BUILD_DATE", "dev")
