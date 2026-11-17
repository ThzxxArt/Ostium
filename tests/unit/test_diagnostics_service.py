"""Diagnostics helpers must report a stage instead of a bare exception."""

from __future__ import annotations

import socket
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx

from ostium.config import Role, Settings
from ostium.engine.dns import DnsProbeResult
from ostium.services import diagnostics


def _settings(role: Role, **overrides: object) -> Settings:
    data = Path("/tmp/opencode/diag")
    values: dict[str, object] = {
        "role": role,
        "data_dir": data,
        "config_dir": data,
        "state_dir": data,
        "core_token_file": data / "token",
        "dev": True,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_answers_filters_to_a_and_aaaa() -> None:
    payload = {
        "Answer": [
            {"type": 5, "data": "cname.example."},
            {"type": 1, "data": "1.2.3.4"},
            {"type": 28, "data": "::1"},
        ]
    }
    assert diagnostics._answers(payload) == ["1.2.3.4", "::1"]


def test_tls_probe_reports_dns_stage(monkeypatch) -> None:
    def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    result = diagnostics.tls_probe("missing.example")
    assert result["ok"] is False
    assert result["stage"] == "dns"
    assert "no such host" in result["error"]


def test_http_probe_reports_tcp_stage() -> None:
    with respx.mock:
        respx.get("https://blocked.example/").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        result = diagnostics.http_probe("https://blocked.example/", timeout=1)
    assert result["ok"] is False
    assert result["stage"] == "tcp"


def test_http_probe_reports_timeout_as_tls_stage() -> None:
    with respx.mock:
        respx.get("https://slow.example/").mock(side_effect=httpx.ReadTimeout("slow"))
        result = diagnostics.http_probe("https://slow.example/", timeout=1)
    assert result["ok"] is False
    assert result["stage"] == "tls"


@pytest.mark.asyncio
async def test_selftest_server_uses_direct_tls(monkeypatch) -> None:
    settings = _settings(Role.SERVER)
    services = SimpleNamespace(settings=settings)

    monkeypatch.setattr(
        diagnostics,
        "tls_probe",
        lambda host: {
            "ok": True,
            "host": host,
            "port": 443,
            "stage": "tls",
            "latency_ms": 12,
            "error": None,
        },
    )
    result = await diagnostics.selftest(services, "google")  # type: ignore[arg-type]
    assert result["ok"] is True
    assert result["mode"] == "direct"
    assert result["stage"] == "tls"


@pytest.mark.asyncio
async def test_selftest_client_uses_proxy(monkeypatch) -> None:
    settings = _settings(Role.CLIENT, mixed_port=7897)
    services = SimpleNamespace(settings=settings)
    calls: list[str | None] = []

    def fake(url: str, *, proxy: str | None = None, timeout: float = 8.0):  # type: ignore[no-untyped-def]
        calls.append(proxy)
        return {
            "ok": True,
            "status_code": 200,
            "stage": "http",
            "latency_ms": 30,
            "error": None,
        }

    monkeypatch.setattr(diagnostics, "http_probe", fake)
    result = await diagnostics.selftest(services, "github")  # type: ignore[arg-type]
    assert result["mode"] == "proxy"
    assert calls == ["http://127.0.0.1:7897"]


def _services(role: Role = Role.SERVER, **overrides: object) -> SimpleNamespace:
    settings = _settings(role, **overrides)
    settings.paths.ensure()

    class Engine:
        def __init__(self) -> None:
            self.client = SimpleNamespace(status=self._status)

        async def _status(self) -> dict[str, object]:
            return {
                "running": True,
                "pid": 42,
                "role": role.value,
                "core_version": "0.1.11",
                "revision": "abc",
                "config_sha256": "0" * 64,
                "last_error": None,
            }

        async def server_preview(self, session: object) -> dict[str, object]:
            return {"log": {"level": "info"}}

        async def client_preview(self, session: object, **kwargs: object) -> dict[str, object]:
            return {"log": {"level": "info"}}

    class Clash:
        async def version(self) -> dict[str, object]:
            return {"version": "1.14.4"}

        async def proxies(self) -> dict[str, object]:
            return {"proxies": {"proxy": {}}}

        async def dns_query(self, domain: str) -> dict[str, object]:
            return {"Answer": [{"type": 1, "data": "142.251.152.119"}]}

    class Proxy:
        def status(self) -> dict[str, object]:
            return {"enabled": False, "supported": True, "platform": "test"}

    return SimpleNamespace(
        settings=settings,
        engine=Engine(),
        clash=Clash(),
        proxy=Proxy(),
        proxy_fail_open_active=False,
        proxy_fail_open_since=None,
        proxy_restore_pending=False,
    )


@pytest.mark.asyncio
async def test_check_version_and_port(monkeypatch) -> None:
    services = _services()
    result = await diagnostics._check_version(services, {"core_version": "9.9.9"})
    assert result.status == "fail"
    assert result.data["mismatches"][0]["surface"] == "core"

    monkeypatch.setattr(
        diagnostics,
        "listener_info",
        lambda port, host=None: {"found": True, "pid": 1, "exe": "/bin/other"},
    )
    port = await diagnostics._check_port(services)
    assert port.status == "warn"

    monkeypatch.setattr(diagnostics, "listener_info", lambda port, host=None: {"found": False})
    port = await diagnostics._check_port(services)
    assert port.status == "fail"


@pytest.mark.asyncio
async def test_check_core_success_and_failure(monkeypatch) -> None:
    services = _services()
    core, checks = await diagnostics._check_core(services)
    assert core["running"] is True
    assert {check.id for check in checks} == {"core_api", "core_running", "core_ready"}

    async def fail() -> dict[str, object]:
        raise RuntimeError("down")

    services.engine.client.status = fail
    core, checks = await diagnostics._check_core(services)
    assert core == {}
    assert {check.id for check in checks} == {"core_api", "core_running", "core_ready"}
    assert all(check.status == "fail" for check in checks)


@pytest.mark.asyncio
async def test_check_config_drift(tmp_path: Path) -> None:
    services = _services()
    meta = services.settings.paths.last_good_meta_path
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text('{"config_sha256": "f' + "0" * 63 + '"}', encoding="utf-8")
    result = await diagnostics._check_config_drift(
        services, SimpleNamespace(), {"config_sha256": "0" * 64}
    )
    assert result.status == "warn"
    assert set(result.data["drift"]) == {"last_good", "running"}

    async def broken(session: object) -> dict[str, object]:
        raise RuntimeError("no profile")

    services.engine.server_preview = broken
    result = await diagnostics._check_config_drift(services, SimpleNamespace(), {})
    assert result.status == "warn"
    assert "could not generate" in result.message


@pytest.mark.asyncio
async def test_check_dns_matches_and_conflicts(monkeypatch) -> None:
    services = _services()

    def probe(url: str, timeout: float = 5.0, name: str = "") -> DnsProbeResult:
        return DnsProbeResult(
            ok=True,
            url=url,
            latency_ms=4.0,
            answers=("142.251.152.119",),
            error=None,
            probed_at="2026-11-17T00:00:00+00:00",
        )

    monkeypatch.setattr(diagnostics, "probe_doh", probe)
    checks = await diagnostics._check_dns(services)
    assert all(check.status == "pass" for check in checks if check.id.startswith("dns_match"))

    async def polluted(domain: str) -> dict[str, object]:
        return {"Answer": [{"type": 1, "data": "104.244.42.197"}]}

    services.clash.dns_query = polluted
    checks = await diagnostics._check_dns(services)
    matches = [check for check in checks if check.id.startswith("dns_match")]
    assert all(check.status == "fail" for check in matches)


@pytest.mark.asyncio
async def test_dns_different_public_cdn_is_warn_not_fail(monkeypatch) -> None:
    services = _services()

    async def different(domain: str) -> dict[str, object]:
        return {"Answer": [{"type": 1, "data": "142.251.155.119"}]}

    services.clash.dns_query = different
    monkeypatch.setattr(
        diagnostics,
        "probe_doh",
        lambda url, timeout=5.0, name="": DnsProbeResult(
            ok=True,
            url=url,
            latency_ms=3.0,
            answers=("142.251.152.119",),
            error=None,
            probed_at="2026-11-17T00:00:00+00:00",
        ),
    )
    checks = await diagnostics._check_dns(services)
    matches = [check for check in checks if check.id.startswith("dns_match")]
    assert matches
    assert all(check.status == "warn" for check in matches)
    assert all("different CDN" in check.message for check in matches)


def test_answers_detect_private_and_pollution_networks() -> None:
    assert diagnostics._looks_polluted(["104.244.42.197"]) is True
    assert diagnostics._looks_polluted(["127.0.0.1"]) is True
    assert diagnostics._looks_polluted(["142.251.152.119"]) is False


@pytest.mark.asyncio
async def test_check_egress_variants(monkeypatch) -> None:
    services = _services()
    monkeypatch.setattr(
        diagnostics,
        "tls_probe",
        lambda host, port=443: {"ok": True, "stage": "tls", "error": None},
    )
    direct = await diagnostics._check_egress(services)
    assert direct.status == "pass"

    client = _services(Role.CLIENT, mixed_port=7897)
    monkeypatch.setattr(
        diagnostics,
        "http_probe",
        lambda url, proxy=None, timeout=8.0: {
            "ok": True,
            "stage": "http",
            "status_code": 200,
            "error": None,
        },
    )
    proxied = await diagnostics._check_egress(client)
    assert proxied.status == "pass"

    monkeypatch.setattr(
        diagnostics,
        "http_probe",
        lambda url, proxy=None, timeout=8.0: {
            "ok": False,
            "stage": "tcp",
            "status_code": None,
            "error": "refused",
        },
    )
    failed = await diagnostics._check_egress(client)
    assert failed.status == "fail"
    assert "tcp" in failed.message


@pytest.mark.asyncio
async def test_check_system_proxy_tun_disk() -> None:
    services = _services(Role.CLIENT)
    core = await diagnostics._check_system_proxy(services, {"running": False})
    assert core.status == "pass"  # fake proxy is disabled

    class EnabledProxy:
        def status(self) -> dict[str, object]:
            return {"enabled": True, "supported": True, "platform": "test"}

    services.proxy = EnabledProxy()
    blackhole = await diagnostics._check_system_proxy(services, {"running": False})
    assert blackhole.status == "fail"

    tun = await diagnostics._check_tun(services)
    assert tun.id == "tun"
    disk = await diagnostics._check_disk(services)
    assert disk.id == "disk"


@pytest.mark.asyncio
async def test_run_checks_in_development_skips_network() -> None:
    services = _services()
    session = SimpleNamespace()

    async def execute(statement: object) -> None:
        return None

    session.execute = execute
    checks = await diagnostics.run_checks(services, session)
    ids = {check.id for check in checks}
    assert "database" in ids
    assert "version_consistency" in ids
    assert "dns_trusted" in ids
    assert "egress" in ids


def test_answers_accepts_string_entries_and_rejects_non_dict() -> None:
    assert diagnostics._answers(None) == []
    assert diagnostics._answers({"Answer": ["1.2.3.4"]}) == ["1.2.3.4"]


def test_tls_probe_success(monkeypatch) -> None:
    class RawSocket:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def settimeout(self, timeout: float) -> None:
            self.timeout = timeout

        def connect(self, address: object) -> None:
            self.address = address

    class TlsSocket(RawSocket):
        def version(self) -> str:
            return "TLSv1.3"

        def cipher(self) -> tuple[str, str, int]:
            return ("TLS_AES_128_GCM_SHA256", "TLSv1.3", 128)

    class Context:
        def wrap_socket(self, raw: RawSocket, server_hostname: str) -> TlsSocket:
            return TlsSocket()

    monkeypatch.setattr(
        diagnostics.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("1.2.3.4", 443))],
    )
    monkeypatch.setattr(diagnostics.socket, "socket", lambda *args: RawSocket())
    monkeypatch.setattr(diagnostics.ssl, "create_default_context", lambda: Context())
    result = diagnostics.tls_probe("www.google.com")
    assert result["ok"] is True
    assert result["stage"] == "tls"
    assert result["tls_version"] == "TLSv1.3"


@pytest.mark.asyncio
async def test_check_config_drift_client_and_clean(tmp_path: Path) -> None:
    services = _services(Role.CLIENT)
    services.settings.paths.last_good_meta_path.unlink(missing_ok=True)
    result = await diagnostics._check_config_drift(
        services, SimpleNamespace(), {"config_sha256": None}
    )
    assert result.status == "pass"
    assert result.data["drift"] == []


@pytest.mark.asyncio
async def test_port_owner_is_current_process(monkeypatch) -> None:
    import os

    services = _services()
    monkeypatch.setattr(
        diagnostics,
        "listener_info",
        lambda port, host=None: {"found": True, "pid": os.getpid(), "exe": "/bin/ostium"},
    )
    result = await diagnostics._check_port(services)
    assert result.status == "pass"


def test_tun_windows_and_disk_warning(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    services = _services(Role.CLIENT)
    monkeypatch.setattr(diagnostics, "os", SimpleNamespace(name="nt"))
    missing = _settings(Role.CLIENT)
    missing.paths.ensure()

    async def _run() -> None:
        services.settings = missing
        result = await diagnostics._check_tun(services)
        assert result.status == "pass"
        assert "wintun" in result.message

    asyncio.run(_run())

    monkeypatch.setattr(diagnostics, "os", SimpleNamespace(name="posix"))
    usage = SimpleNamespace(percent=95, used=95, total=100)
    monkeypatch.setattr(diagnostics.psutil, "disk_usage", lambda path: usage)
    disk = asyncio.run(diagnostics._check_disk(services))
    assert disk.status == "warn"


@pytest.mark.asyncio
async def test_run_checks_network_branch_and_database_failure(monkeypatch) -> None:
    services = _services()
    services.settings.dev = False
    session = SimpleNamespace()

    async def fail(statement: object) -> None:
        raise RuntimeError("locked")

    session.execute = fail

    async def fake_dns(services: object) -> list[diagnostics.CheckResult]:
        return [diagnostics._result("dns_trusted", "pass", "ok")]

    async def fake_egress(services: object) -> diagnostics.CheckResult:
        return diagnostics._result("egress", "pass", "ok")

    monkeypatch.setattr(diagnostics, "_check_dns", fake_dns)
    monkeypatch.setattr(diagnostics, "_check_egress", fake_egress)
    checks = await diagnostics.run_checks(services, session)
    ids = {check.id for check in checks}
    assert "database" in ids
    assert "dns_trusted" in ids
    assert "egress" in ids
    assert next(check for check in checks if check.id == "database").status == "fail"
