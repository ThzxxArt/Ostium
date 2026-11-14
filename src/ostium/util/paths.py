"""Portable storage paths for the database.

Certificates and rule sets used to be stored as absolute paths.  That made a
backup impossible to restore on another machine or under another data
directory.  New rows are stored relative to ``data_dir``; reads accept both
forms so databases created by 0.1.0/0.1.1 keep working.
"""

from __future__ import annotations

from pathlib import Path

from ostium.config import Settings


def store_path(settings: Settings, path: Path | str) -> str:
    """Return a data-dir-relative POSIX path when possible."""

    value = Path(path)
    try:
        return value.resolve().relative_to(settings.data_dir.resolve()).as_posix()
    except (OSError, ValueError):
        # An external certificate path is legal; keep it absolute rather than
        # silently pointing at a different file after a restore.
        return value.resolve().as_posix() if value.is_absolute() else value.as_posix()


def resolve_path(settings: Settings, stored: str | Path | None) -> Path | None:
    """Resolve a stored path, accepting both relative and legacy absolute rows."""

    if stored is None or str(stored) == "":
        return None
    value = Path(stored)
    if value.is_absolute():
        return value
    return (settings.data_dir / value).resolve()
