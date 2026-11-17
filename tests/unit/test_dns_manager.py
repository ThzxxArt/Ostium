"""The server DNS policy must be selected once, cached and explicit."""

from __future__ import annotations

import pytest

from ostium.config import Role, Settings
from ostium.engine import manager as manager_module
from ostium.engine.dns import DnsProbeResult
from ostium.engine.manager import EngineError, EngineManager
from ostium.services.events import EventBus


def _probe(ok: bool) -> DnsProbeResult:
    return DnsProbeResult(
        ok=ok,
        url="https://1.1.1.1/dns-query",
        latency_ms=5.0 if ok else None,
        answers=("1.2.3.4",) if ok else (),
        error=None if ok else "blocked",
        probed_at="2026-11-17T00:00:00+00:00",
    )


def _manager(settings: Settings) -> EngineManager:
    return EngineManager(settings, None, None, EventBus())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_auto_falls_back_to_udp(settings: Settings, monkeypatch) -> None:
    settings.role = Role.SERVER
    settings.server_dns_mode = "auto"
    manager = _manager(settings)
    monkeypatch.setattr(manager_module, "probe_doh", lambda url: _probe(False))
    selection = await manager.refresh_server_dns(force=True)
    assert selection is not None
    assert selection.mode == "udp"
    assert selection.probe_error == "blocked"


@pytest.mark.asyncio
async def test_doh_mode_fails_closed(settings: Settings, monkeypatch) -> None:
    settings.role = Role.SERVER
    settings.server_dns_mode = "doh"
    manager = _manager(settings)
    monkeypatch.setattr(manager_module, "probe_doh", lambda url: _probe(False))
    with pytest.raises(EngineError, match="DoH is required"):
        await manager.refresh_server_dns(force=True)
    assert manager.server_dns is None


@pytest.mark.asyncio
async def test_probe_result_is_cached(settings: Settings, monkeypatch) -> None:
    settings.role = Role.SERVER
    settings.server_dns_mode = "auto"
    manager = _manager(settings)
    calls: list[str] = []

    def probe(url: str) -> DnsProbeResult:
        calls.append(url)
        return _probe(True)

    monkeypatch.setattr(manager_module, "probe_doh", probe)
    first = await manager.refresh_server_dns(force=True)
    second = await manager.refresh_server_dns()
    assert first is not None and second is not None
    assert first.mode == second.mode == "doh"
    assert calls == [settings.server_dns_doh_url]


@pytest.mark.asyncio
async def test_udp_mode_never_probes(settings: Settings, monkeypatch) -> None:
    settings.role = Role.SERVER
    settings.server_dns_mode = "udp"
    manager = _manager(settings)

    def probe(url: str) -> DnsProbeResult:
        raise AssertionError("UDP mode must not probe DoH")

    monkeypatch.setattr(manager_module, "probe_doh", probe)
    selection = await manager.refresh_server_dns(force=True)
    assert selection is not None
    assert selection.mode == "udp"
    assert selection.probed_at is None
