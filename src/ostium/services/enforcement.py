"""Fail-closed enforcement state shared by the control plane and the core.

The control plane is the source of truth for which users are disabled.  The
privileged core, however, starts from ``last-good.json`` and may be restarted
independently (systemd, a crash, or an upgrade).  If the last-good file predates
a quota/expiry decision, restarting the core would silently resurrect a user
that the database already disabled.

This module persists the disabled-user policy next to the database in a small
atomically-replaced file.  The core strips those users from the last-good
configuration before it validates or spawns sing-box, so a restart cannot grant
access that the control plane has revoked.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ENFORCEMENT_VERSION = 1
DISABLED_REASONS = frozenset({"quota_exceeded", "expired"})


def write_enforcement(path: Path, names: set[str] | list[str]) -> None:
    """Atomically persist the set of users that must never be served."""

    payload = {
        "version": ENFORCEMENT_VERSION,
        "users": sorted({str(name) for name in names if str(name)}),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if os.name == "posix":
        temporary.chmod(0o600)
    temporary.replace(path)


def read_enforcement(path: Path) -> set[str]:
    """Read the persisted policy; a missing/corrupt file means "no overrides"."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(payload, dict) or payload.get("version") != ENFORCEMENT_VERSION:
        return set()
    users = payload.get("users")
    if not isinstance(users, list):
        return set()
    return {str(item) for item in users if isinstance(item, str) and item}


def strip_disabled_users(config: dict[str, Any], disabled: set[str]) -> tuple[dict[str, Any], bool]:
    """Return a copy of a server config without revoked users.

    A server config stores the same user list in every inbound.  Only entries
    that carry a ``name`` are removed; a static credential without a name is
    left untouched because it cannot be tied to a database user.
    """

    if not disabled:
        return config, False
    changed = False
    clone: dict[str, Any] = {**config}
    inbounds = config.get("inbounds")
    if not isinstance(inbounds, list):
        return config, False
    cloned_inbounds: list[Any] = []
    for inbound in inbounds:
        if not isinstance(inbound, dict):
            cloned_inbounds.append(inbound)
            continue
        users = inbound.get("users")
        if not isinstance(users, list):
            cloned_inbounds.append(inbound)
            continue
        kept = [
            user for user in users if not (isinstance(user, dict) and user.get("name") in disabled)
        ]
        if len(kept) == len(users):
            cloned_inbounds.append(inbound)
            continue
        changed = True
        updated = {**inbound, "users": kept}
        cloned_inbounds.append(updated)
    if changed:
        clone["inbounds"] = cloned_inbounds
    return clone, changed
