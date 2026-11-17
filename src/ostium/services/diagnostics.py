"""Layered diagnostics for the control plane, core and egress path.

The old doctor only reported "database, core, engine, proxy".  That cannot
answer the questions operators actually have after an upgrade: is the process
on the port the expected build, is DNS polluted, is the failure DNS/TCP/TLS,
and does the database configuration match what the core is running?

Every network check is bounded and runs off the event loop.  Results never
contain credentials; URLs and domains are already public by design.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import ssl
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psutil
from sqlalchemy import text

from ostium.build_info import build_info, listener_info, read_web_build, version_mismatches
from ostium.engine.dns import probe_doh
from ostium.engine.singbox.config import config_digest
from ostium.util.time import iso, utcnow

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ostium.api.deps import Services

SELFTEST_TARGETS = {
    "google": ("www.google.com", "https://www.google.com/"),
    "huggingface": ("huggingface.co", "https://huggingface.co/"),
    "github": ("github.com", "https://github.com/"),
}
DNS_PROBE_DOMAINS = {
    "google": "www.google.com",
    "huggingface": "huggingface.co",
    "github": "github.com",
}
NETWORK_TIMEOUT = 8.0


@dataclass
class CheckResult:
    id: str
    status: str
    message: str
    fix: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "fix": self.fix,
            "data": self.data,
            "duration_ms": self.duration_ms,
        }


def _result(
    check_id: str,
    status: str,
    message: str,
    *,
    fix: str | None = None,
    data: dict[str, Any] | None = None,
    started: float | None = None,
) -> CheckResult:
    duration = None if started is None else int((time.monotonic() - started) * 1000)
    return CheckResult(
        id=check_id,
        status=status,
        message=message,
        fix=fix,
        data=data or {},
        duration_ms=duration,
    )


def tls_probe(host: str, port: int = 443, timeout: float = NETWORK_TIMEOUT) -> dict[str, Any]:
    """Direct TLS handshake with explicit stage reporting."""

    started = time.monotonic()
    stage = "dns"
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not addresses:
            raise OSError("no addresses returned")
        stage = "tcp"
        last_error: Exception | None = None
        for family, socktype, proto, _, sockaddr in addresses:
            try:
                with socket.socket(family, socktype, proto) as raw:
                    raw.settimeout(timeout)
                    raw.connect(sockaddr)
                    stage = "tls"
                    context = ssl.create_default_context()
                    with context.wrap_socket(raw, server_hostname=host) as tls:
                        version = tls.version()
                        cipher = tls.cipher()
                return {
                    "ok": True,
                    "host": host,
                    "port": port,
                    "stage": "tls",
                    "tls_version": version,
                    "cipher": cipher[0] if cipher else None,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "error": None,
                }
            except Exception as exc:  # try the next address
                last_error = exc
        raise last_error or OSError("no usable address")
    except Exception as exc:
        return {
            "ok": False,
            "host": host,
            "port": port,
            "stage": stage,
            "tls_version": None,
            "cipher": None,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": str(exc) or exc.__class__.__name__,
        }


def http_probe(
    url: str,
    *,
    proxy: str | None = None,
    timeout: float = NETWORK_TIMEOUT,
) -> dict[str, Any]:
    """HTTP(S) request with a bounded timeout and a coarse failure stage."""

    import httpx

    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(4.0, timeout)),
            proxy=proxy,
            trust_env=False,
            follow_redirects=True,
        ) as client:
            response = client.get(url)
        return {
            "ok": response.status_code < 500,
            "url": url,
            "status_code": response.status_code,
            "stage": "http",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": None,
        }
    except Exception as exc:
        name = exc.__class__.__name__.lower()
        if "ssl" in name:
            stage = "tls"
        elif "connect" in name or "network" in name or "proxy" in name:
            stage = "tcp"
        elif "timeout" in name:
            stage = "tls"
        else:
            stage = "http"
        return {
            "ok": False,
            "url": url,
            "status_code": None,
            "stage": stage,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": str(exc) or exc.__class__.__name__,
        }


def _answers(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    values: list[str] = []
    answer = payload.get("Answer") or payload.get("answer") or []
    if isinstance(answer, list):
        for entry in answer:
            if isinstance(entry, dict):
                if entry.get("type") in {1, "1", 28, "28"} and entry.get("data"):
                    values.append(str(entry["data"]))
            elif isinstance(entry, str):
                values.append(entry)
    return sorted(set(values))


async def _check_version(services: Services, core: dict[str, Any]) -> CheckResult:
    started = time.monotonic()
    build = build_info()
    web = read_web_build(services.settings.paths.web_dist)
    web_version = str(web.get("version")) if web.get("available") and web.get("version") else None
    core_version = str(core["core_version"]) if core.get("core_version") else None
    mismatches = version_mismatches(build.version, core=core_version, web=web_version)
    return _result(
        "version_consistency",
        "pass" if not mismatches else "fail",
        "control plane, core and Web bundle versions match"
        if not mismatches
        else "; ".join(
            f"{item['surface']} reports {item['actual']} (expected {item['expected']})"
            for item in mismatches
        ),
        fix=None if not mismatches else "stop the stale process and install the expected release",
        data={
            "expected": build.version,
            "commit": build.commit,
            "core": core_version,
            "web": web_version,
            "web_build": web,
            "mismatches": mismatches,
        },
        started=started,
    )


async def _check_port(services: Services) -> CheckResult:
    started = time.monotonic()
    owner = await asyncio.to_thread(
        listener_info, services.settings.port, host=services.settings.host
    )
    if not owner.get("found"):
        return _result(
            f"port_owner:{services.settings.port}",
            "fail",
            f"nothing is listening on {services.settings.host}:{services.settings.port}",
            fix="start the control plane",
            data=owner,
            started=started,
        )
    if owner.get("pid") != os.getpid():
        return _result(
            f"port_owner:{services.settings.port}",
            "warn",
            f"port is owned by pid {owner.get('pid')} ({owner.get('exe')}), not this process",
            fix="stop the stale process or start the expected control plane",
            data=owner,
            started=started,
        )
    return _result(
        f"port_owner:{services.settings.port}",
        "pass",
        f"listener pid {owner.get('pid')} is this process",
        data=owner,
        started=started,
    )


async def _check_core(services: Services) -> tuple[dict[str, Any], list[CheckResult]]:
    checks: list[CheckResult] = []
    started = time.monotonic()
    try:
        core = await asyncio.wait_for(services.engine.client.status(), timeout=3)
    except Exception as exc:
        core = {}
        checks.append(
            _result(
                "core_api",
                "fail",
                f"core API unreachable: {exc}",
                fix="start ostium-core.service",
                started=started,
            )
        )
        checks.append(
            _result(
                "core_running",
                "fail",
                "core state cannot be checked while the API is unreachable",
                started=started,
            )
        )
        checks.append(
            _result(
                "core_ready",
                "fail",
                "Clash API cannot be checked while the core API is unreachable",
                started=started,
            )
        )
        return core, checks
    checks.append(
        _result(
            "core_api",
            "pass",
            "core API is reachable",
            data={"role": core.get("role"), "version": core.get("core_version")},
            started=started,
        )
    )
    checks.append(
        _result(
            "core_running",
            "pass" if core.get("running") else "warn",
            f"sing-box is running (pid {core.get('pid')})"
            if core.get("running")
            else "sing-box is not running",
            fix=None if core.get("running") else "apply the configuration",
            data={
                "pid": core.get("pid"),
                "revision": core.get("revision"),
                "last_error": core.get("last_error"),
            },
        )
    )
    clash_version = await services.clash.version()
    clash_proxies = await services.clash.proxies() if clash_version else {}
    ready = bool(clash_version) and bool(clash_proxies)
    checks.append(
        _result(
            "core_ready",
            "pass" if ready else "warn",
            f"Clash API ready ({len(clash_proxies.get('proxies') or {})} proxies)"
            if ready
            else "Clash API is not ready",
            fix=None if ready else "check the core log for a failed bind or config load",
            data={
                "version": clash_version,
                "proxy_count": len((clash_proxies or {}).get("proxies") or {}),
            },
        )
    )
    return core, checks


async def _check_config_drift(
    services: Services, session: AsyncSession, core: dict[str, Any]
) -> CheckResult:
    started = time.monotonic()
    try:
        if services.settings.role.value == "server":
            preview = await services.engine.server_preview(session)
        else:
            preview = await services.engine.client_preview(session)
        expected = config_digest(preview)
    except Exception as exc:
        return _result(
            "config_drift",
            "warn",
            f"could not generate the current configuration: {exc}",
            started=started,
        )
    running = core.get("config_sha256")
    last_good: dict[str, Any] = {}
    meta_path = services.settings.paths.last_good_meta_path
    if meta_path.is_file():
        with contextlib.suppress(OSError, ValueError):
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            last_good = loaded if isinstance(loaded, dict) else {}
    mismatches = []
    if running and running != expected:
        mismatches.append("running")
    if last_good.get("config_sha256") and last_good["config_sha256"] != expected:
        mismatches.append("last_good")
    return _result(
        "config_drift",
        "pass" if not mismatches else "warn",
        "database configuration matches the running core"
        if not mismatches
        else f"configuration drift detected: {', '.join(mismatches)}",
        fix=None if not mismatches else "re-apply the configuration",
        data={
            "expected_sha256": expected,
            "core_sha256": running,
            "last_good_sha256": last_good.get("config_sha256"),
            "drift": mismatches,
        },
        started=started,
    )


async def _check_dns(services: Services) -> list[CheckResult]:
    checks: list[CheckResult] = []
    doh_url = services.settings.server_dns_doh_url
    for label, domain in DNS_PROBE_DOMAINS.items():
        started = time.monotonic()
        core_answer = await services.clash.dns_query(domain)
        trusted = await asyncio.to_thread(probe_doh, doh_url, timeout=4.0, name=domain)
        core_values = _answers(core_answer)
        trusted_values = list(trusted.answers)
        checks.append(
            _result(
                f"dns_singbox:{label}",
                "pass" if core_values else "warn",
                f"core resolved {domain} to {', '.join(core_values)}"
                if core_values
                else f"core returned no A record for {domain}",
                fix=None if core_values else "check the core DNS server and core.log",
                data={"domain": domain, "answers": core_values},
                started=started,
            )
        )
        checks.append(
            _result(
                f"dns_trusted:{label}",
                "pass" if trusted.ok else "warn",
                f"DoH resolved {domain} to {', '.join(trusted_values)}"
                if trusted.ok
                else f"DoH probe failed: {trusted.error}",
                data={
                    "domain": domain,
                    "answers": trusted_values,
                    "latency_ms": trusted.latency_ms,
                    "error": trusted.error,
                },
            )
        )
        conflict = bool(
            core_values and trusted_values and not set(core_values) & set(trusted_values)
        )
        checks.append(
            _result(
                f"dns_match:{label}",
                "fail" if conflict else ("pass" if core_values and trusted_values else "warn"),
                f"{domain} resolves to a conflicting address set"
                if conflict
                else f"{domain} resolution is consistent"
                if core_values and trusted_values
                else f"{domain} comparison is incomplete",
                fix=None if not conflict else "switch server_dns_mode to doh and re-apply",
                data={"domain": domain, "core": core_values, "trusted": trusted_values},
            )
        )
    return checks


async def _check_egress(services: Services) -> CheckResult:
    started = time.monotonic()
    if services.settings.role.value == "server":
        result = await asyncio.to_thread(tls_probe, "www.google.com")
        result_hf = await asyncio.to_thread(tls_probe, "huggingface.co")
        ok = bool(result["ok"] and result_hf["ok"])
        return _result(
            "egress_direct",
            "pass" if ok else "fail",
            "direct TLS to Google and Hugging Face succeeded"
            if ok
            else (
                f"direct egress failed at {result['stage']}: "
                f"{result['error'] or result_hf['error']}"
            ),
            fix=None if ok else "check DNS, TCP egress and the server firewall",
            data={"google": result, "huggingface": result_hf},
            started=started,
        )
    proxy_url = f"http://127.0.0.1:{services.settings.mixed_port}"
    google = await asyncio.to_thread(http_probe, "https://www.google.com/", proxy=proxy_url)
    hf = await asyncio.to_thread(http_probe, "https://huggingface.co/", proxy=proxy_url)
    ok = bool(google["ok"] and hf["ok"])
    return _result(
        "egress_proxy",
        "pass" if ok else "fail",
        "proxy TLS to Google and Hugging Face succeeded"
        if ok
        else f"proxy egress failed at {google['stage']}: {google['error'] or hf['error']}",
        fix=None if ok else "check the profile, core state and the proxy port",
        data={"google": google, "huggingface": hf},
        started=started,
    )


async def _check_system_proxy(services: Services, core: dict[str, Any]) -> CheckResult:
    started = time.monotonic()
    if services.settings.role.value != "client":
        return _result(
            "system_proxy",
            "pass",
            "system proxy is a client feature",
            data={"supported": False},
            started=started,
        )
    status = await asyncio.to_thread(lambda: services.proxy.status())
    enabled = bool(status.get("enabled"))
    blackhole = enabled and not core.get("running")
    return _result(
        "system_proxy",
        "fail" if blackhole else ("pass" if status.get("supported") else "warn"),
        "system proxy points at a stopped core; traffic will blackhole"
        if blackhole
        else f"system proxy {'enabled' if enabled else 'disabled'} ({status.get('platform')})",
        fix="disconnect or restore the core" if blackhole else None,
        data=status,
        started=started,
    )


async def _check_tun(services: Services) -> CheckResult:
    started = time.monotonic()
    if services.settings.role.value != "client":
        return _result("tun", "pass", "TUN is a client feature", started=started)
    if os.name == "nt":
        available = True
        detail = "Windows TUN uses the bundled wintun driver"
    else:
        available = os.geteuid() == 0 or Path("/dev/net/tun").exists()
        detail = (
            "/dev/net/tun is available"
            if available
            else "/dev/net/tun is not available or this user lacks CAP_NET_ADMIN"
        )
    return _result(
        "tun",
        "pass" if available else "warn",
        detail,
        fix=None if available else "start the privileged core with CAP_NET_ADMIN",
        data={"available": available},
        started=started,
    )


async def _check_disk(services: Services) -> CheckResult:
    started = time.monotonic()
    usage = psutil.disk_usage(str(services.settings.data_dir))
    return _result(
        "disk",
        "pass" if usage.percent < 90 else "warn",
        f"data directory is {usage.percent:.0f}% full",
        fix=None if usage.percent < 90 else "free space or move backups",
        data={"percent": usage.percent, "used": usage.used, "total": usage.total},
        started=started,
    )


async def run_checks(services: Services, session: AsyncSession) -> list[CheckResult]:
    """Run every check that does not need an authenticated HTTP request."""

    started = time.monotonic()
    checks: list[CheckResult] = []
    try:
        await session.execute(text("SELECT 1"))
        checks.append(_result("database", "pass", "SQLite database is readable", started=started))
    except Exception as exc:
        checks.append(
            _result(
                "database",
                "fail",
                f"database check failed: {exc}",
                fix="check data directory permissions",
                started=started,
            )
        )
    checks.append(await _check_port(services))
    core, core_checks = await _check_core(services)
    checks.extend(core_checks)
    checks.append(await _check_version(services, core))
    checks.append(await _check_config_drift(services, session, core))
    engine = Path(services.settings.engine_path or services.settings.paths.engine_binary)
    checks.append(
        _result(
            "engine_binary",
            "pass" if engine.is_file() else "fail",
            f"core binary found at {engine}"
            if engine.is_file()
            else f"core binary missing at {engine}",
            fix=None if engine.is_file() else "run `ostium core install`",
            data={"path": str(engine)},
        )
    )
    if services.settings.dev:
        checks.append(
            _result(
                "dns_trusted",
                "warn",
                "network DNS probes are skipped in development mode",
            )
        )
        checks.append(
            _result(
                "egress",
                "warn",
                "network egress probes are skipped in development mode",
            )
        )
    else:
        checks.extend(await _check_dns(services))
        checks.append(await _check_egress(services))
    checks.append(await _check_system_proxy(services, core))
    checks.append(await _check_tun(services))
    checks.append(await _check_disk(services))
    return checks


async def selftest(services: Services, target: str) -> dict[str, Any]:
    host, url = SELFTEST_TARGETS[target]
    if services.settings.role.value == "server":
        result = await asyncio.to_thread(tls_probe, host)
    else:
        proxy_url = f"http://127.0.0.1:{services.settings.mixed_port}"
        result = await asyncio.to_thread(http_probe, url, proxy=proxy_url)
    return {
        "ok": bool(result["ok"]),
        "target": target,
        "host": host,
        "mode": "direct" if services.settings.role.value == "server" else "proxy",
        "stage": result["stage"],
        "latency_ms": result["latency_ms"],
        "status_code": result.get("status_code"),
        "error": result.get("error"),
        "generated_at": iso(utcnow()) or "",
    }
