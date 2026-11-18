"""Operational doctor: actionable, non-destructive health checks."""

from __future__ import annotations

import socket
from dataclasses import asdict, dataclass

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django_otp.plugins.otp_totp.models import TOTPDevice

from ostium import paths
from ostium.certificates.models import Certificate
from ostium.engine.dns import doh_available
from ostium.engine.supervisor import disk_free_bytes, verify_binary
from ostium.operations.models import RuntimeState

from .models import Alert


@dataclass(slots=True)
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def run_doctor() -> list[dict]:
    checks: list[Check] = []

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks.append(Check("Database", "pass", "Connection is healthy."))
    except Exception as exc:
        checks.append(Check("Database", "fail", str(exc), "Check OSTIUM_DB_URL and database permissions."))

    try:
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if pending:
            checks.append(Check("Migrations", "fail", f"{len(pending)} unapplied migration(s).", "Run: ostium migrate"))
        else:
            checks.append(Check("Migrations", "pass", "All migrations are applied."))
    except Exception as exc:
        checks.append(Check("Migrations", "warn", str(exc), "Run: ostium migrate"))

    try:
        paths.ensure()
        probe = paths.runtime_dir() / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(Check("Data directory", "pass", f"{paths.data_dir()} is writable."))
    except OSError as exc:
        checks.append(Check("Data directory", "fail", str(exc), "Fix ownership of the data directory."))

    free = disk_free_bytes()
    if free < 1024**3:
        checks.append(Check("Disk space", "fail", f"{free / 1024**3:.1f} GiB free.", "Free disk space."))
    elif free < 5 * 1024**3:
        checks.append(Check("Disk space", "warn", f"{free / 1024**3:.1f} GiB free.", "Plan a cleanup."))
    else:
        checks.append(Check("Disk space", "pass", f"{free / 1024**3:.1f} GiB free."))

    ok, message = verify_binary()
    checks.append(
        Check(
            "sing-box binary",
            "pass" if ok else "fail",
            message,
            "Install the pinned sing-box binary and set OSTIUM_SINGBOX_PATH." if not ok else "",
        )
    )

    state = RuntimeState.load()
    if state.worker_alive:
        checks.append(Check("Worker heartbeat", "pass", f"Last heartbeat {state.heartbeat_age:.0f}s ago."))
    else:
        checks.append(Check("Worker heartbeat", "fail", "Worker heartbeat is stale.", "Start ostium-worker.service."))
    if state.singbox_running:
        checks.append(Check("sing-box process", "pass", f"PID {state.singbox_pid}."))
    else:
        checks.append(Check("sing-box process", "fail", "Not running.", "Check ostium-worker logs."))
    if state.last_error:
        checks.append(
            Check("Last apply", "warn", state.last_error[:400], "Fix the configuration and run ostium apply.")
        )
    else:
        checks.append(Check("Last apply", "pass", f"Revision {state.applied_revision} applied."))

    checks.append(
        Check(
            "Management port",
            "pass" if _port_open("127.0.0.1", 8000) else "warn",
            "127.0.0.1:8000 is listening." if _port_open("127.0.0.1", 8000) else "127.0.0.1:8000 is closed.",
            "Start ostium-web.service; the API/UI bind to loopback by default.",
        )
    )

    if doh_available("https://1.1.1.1/dns-query"):
        checks.append(Check("DoH", "pass", "1.1.1.1 DNS-over-HTTPS is reachable."))
    else:
        checks.append(Check("DoH", "warn", "DoH probe failed.", "The worker can fall back to UDP DNS (auto mode)."))

    soon = [cert for cert in Certificate.objects.all() if cert.days_remaining <= 30]
    if soon:
        checks.append(
            Check(
                "Certificates",
                "warn",
                ", ".join(f"{cert.domain} ({cert.days_remaining}d)" for cert in soon[:5]),
                "Renew certificates with certbot or import a new pair.",
            )
        )
    else:
        checks.append(Check("Certificates", "pass", "No certificate expires within 30 days."))

    if not TOTPDevice.objects.filter(confirmed=True).exists():
        checks.append(
            Check(
                "Two-factor authentication",
                "warn",
                "No confirmed TOTP device.",
                "Enable TOTP before exposing the console.",
            )
        )
    else:
        checks.append(Check("Two-factor authentication", "pass", "A TOTP device is configured."))

    if settings.ALLOWED_HOSTS == ["*"]:
        checks.append(
            Check(
                "ALLOWED_HOSTS",
                "warn",
                "Wildcard allowed hosts.",
                "Set OSTIUM_ALLOWED_HOSTS to the public hostname.",
            )
        )
    else:
        checks.append(Check("ALLOWED_HOSTS", "pass", ", ".join(settings.ALLOWED_HOSTS)))

    if settings.OSTIUM_REQUIRE_TOTP or settings.OSTIUM_PUBLIC_BASE_URL.startswith("https://"):
        checks.append(Check("Console exposure", "pass", "Public exposure requires TOTP and TLS."))
    else:
        checks.append(Check("Console exposure", "pass", "Console is intended for loopback or an SSH tunnel."))

    unack = Alert.objects.filter(acknowledged_at__isnull=True).count()
    checks.append(
        Check(
            "Alerts",
            "pass" if unack == 0 else "warn",
            f"{unack} unacknowledged alert(s).",
            "Review the dashboard alert list." if unack else "",
        )
    )

    return [asdict(check) for check in checks]


def doctor_summary(checks: list[dict]) -> dict:
    return {
        "pass": sum(1 for check in checks if check["status"] == "pass"),
        "warn": sum(1 for check in checks if check["status"] == "warn"),
        "fail": sum(1 for check in checks if check["status"] == "fail"),
    }
