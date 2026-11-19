"""Filesystem layout for runtime data.

All mutable state lives under ``OSTIUM_DATA_DIR``. The web process, worker and
Django-Q cluster share the same directory; permissions are tightened on every
startup so that generated secrets are never world readable.
"""

from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings


def data_dir() -> Path:
    return Path(settings.OSTIUM_DATA_DIR).resolve()


def runtime_dir() -> Path:
    return data_dir() / "runtime"


def secrets_dir() -> Path:
    return data_dir() / "secrets"


def backup_password_path() -> Path:
    return secrets_dir() / "backup-password"


def certs_dir() -> Path:
    return data_dir() / "certs"


def logs_dir() -> Path:
    return data_dir() / "logs"


def backups_dir() -> Path:
    return data_dir() / "backups"


def imports_dir() -> Path:
    return data_dir() / "imports"


def config_path() -> Path:
    return runtime_dir() / "config.json"


def previous_config_path() -> Path:
    return runtime_dir() / "config.previous.json"


def next_config_path() -> Path:
    return runtime_dir() / "config.next.json"


def usage_path() -> Path:
    return runtime_dir() / "usage.json"


def worker_lock_path() -> Path:
    return runtime_dir() / "worker.lock"


def worker_pid_path() -> Path:
    return runtime_dir() / "worker.pid"


def clash_secret_path() -> Path:
    return runtime_dir() / "clash.secret"


def singbox_log_path() -> Path:
    return logs_dir() / "sing-box.log"


def ostium_log_path() -> Path:
    return logs_dir() / "ostium.log"


_DIRECTORIES = (data_dir, runtime_dir, secrets_dir, certs_dir, logs_dir, backups_dir, imports_dir)


def ensure() -> None:
    """Create the data tree with restrictive permissions."""

    for factory in _DIRECTORIES:
        path = factory()
        path.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def secure_file(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
