"""Redacted diagnostic bundle generation."""

from __future__ import annotations

import io
import json
import platform
import socket
import sys
import tarfile

import psutil
from django.conf import settings
from django.utils import timezone

from ostium import paths
from ostium.engine.runtime import read_usage, tail_file
from ostium.engine.supervisor import binary_version
from ostium.operations.models import RuntimeState
from ostium.redaction import redact
from ostium.version import BUILD_COMMIT, BUILD_DATE, __version__

from .doctor import doctor_summary, run_doctor


def _add(tar: tarfile.TarFile, name: str, data: str) -> None:
    raw = data.encode("utf-8")
    info = tarfile.TarInfo(name)
    info.size = len(raw)
    info.mtime = int(timezone.now().timestamp())
    tar.addfile(info, io.BytesIO(raw))


def build_diagnostics() -> bytes:
    state = RuntimeState.load()
    doctor = run_doctor()
    try:
        config_text = paths.config_path().read_text(encoding="utf-8")
    except OSError:
        config_text = ""
    logs = {
        "ostium.log": redact(tail_file(paths.ostium_log_path(), max_bytes=512 * 1024)),
        "sing-box.log": redact(tail_file(paths.singbox_log_path(), max_bytes=512 * 1024)),
    }
    system = {
        "platform": platform.platform(),
        "python": sys.version,
        "cpu_count": psutil.cpu_count(),
        "memory": psutil.virtual_memory()._asdict(),
        "disk": psutil.disk_usage(str(paths.data_dir()))._asdict(),
        "hostname": socket.gethostname(),
        "boot_time": timezone.datetime.fromtimestamp(
            psutil.boot_time(), tz=timezone.get_current_timezone()
        ).isoformat(),
    }
    runtime = {
        "version": __version__,
        "build_commit": BUILD_COMMIT,
        "build_date": BUILD_DATE,
        "state": {
            "desired_revision": state.desired_revision,
            "applied_revision": state.applied_revision,
            "singbox_running": state.singbox_running,
            "worker_alive": state.worker_alive,
            "last_error": redact(state.last_error),
        },
        "usage": read_usage(),
        "singbox_version": binary_version(),
        "doctor": {"summary": doctor_summary(doctor), "checks": doctor},
        "settings": {
            "debug": settings.DEBUG,
            "allowed_hosts": settings.ALLOWED_HOSTS,
            "require_totp": settings.OSTIUM_REQUIRE_TOTP,
            "public_base_url": settings.OSTIUM_PUBLIC_BASE_URL,
            "data_dir": str(paths.data_dir()),
            "behind_proxy": settings.OSTIUM_BEHIND_PROXY,
            "db_engine": settings.DATABASES["default"]["ENGINE"],
        },
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        _add(tar, "runtime.json", json.dumps(runtime, indent=2, default=str))
        _add(tar, "system.json", json.dumps(system, indent=2, default=str))
        _add(tar, "config.redacted.json", redact(config_text, max_length=2 * 1024 * 1024))
        for name, content in logs.items():
            _add(tar, f"logs/{name}", content)
    return buffer.getvalue()
