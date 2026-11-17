"""Diagnostics helpers must report a stage instead of a bare exception."""

from __future__ import annotations

import socket
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx

from ostium.config import Role, Settings
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
