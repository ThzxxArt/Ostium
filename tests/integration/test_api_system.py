from __future__ import annotations

import io
import json
import sqlite3
import tarfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from ostium.config import Settings
from ostium.engine.core_api import CoreApiError
from ostium.engine.manager import EngineError
from ostium.util.time import utcnow
from tests.conftest import setup_admin


def _headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


class FakeProxy:
    def __init__(self) -> None:
        self.enabled = False
        self.supported = True
        self.fail_enable = False
        self.fail_disable = False
        self.calls: list[str] = []

    def status(self) -> dict:
        return {
            "supported": self.supported,
            "platform": "test",
            "enabled": self.enabled,
            "host": "127.0.0.1",
            "port": 7890,
        }

    def enable(self, host: str = "127.0.0.1", port: int | None = None) -> dict:
        self.calls.append("enable")
        if self.fail_enable:
            raise RuntimeError("cannot enable")
        self.enabled = True
        return self.status()

    def disable(self) -> dict:
        self.calls.append("disable")
        if self.fail_disable:
            raise RuntimeError("cannot disable")
        self.enabled = False
        return self.status()


@pytest.fixture
def fake_proxy(monkeypatch) -> FakeProxy:  # type: ignore[no-untyped-def]
    proxy = FakeProxy()
    monkeypatch.setattr("ostium.api.deps.system_proxy", lambda settings: proxy)
    return proxy


def _sql(settings: Settings, statement: str, params: tuple[object, ...] = ()) -> None:
    with sqlite3.connect(settings.paths.db_path) as connection:
        connection.execute(statement, params)
        connection.commit()


def test_server_system_info_doctor_and_diagnostics(
    api_client: TestClient, session_token: str, settings: Settings, fake_proxy: FakeProxy
) -> None:
    async def running() -> dict:
        return {"running": True, "pid": 123, "revision": "r1", "engine_version": "1.14.4"}

    api_client.app.state.services.engine.client.status = running  # type: ignore[method-assign]
    info = api_client.get("/api/v1/system/info")
    assert info.status_code == 200
    payload = info.json()
    assert payload["app"]["role"] == "server"
    assert payload["server_host"] == "example.com"
    assert payload["core"]["running"] is True
    assert payload["proxy"]["platform"] == "test"
    assert payload["allow_lan"] is False
    assert isinstance(payload["lan_addresses"], list)
    assert payload["lan_port"] == settings.mixed_port

    settings.engine_path = settings.data_dir / "missing-sing-box"
    doctor = api_client.get("/api/v1/system/doctor").json()
    statuses = {(check["id"], check["status"]) for check in doctor["checks"]}
    assert ("database", "pass") in statuses
    assert ("core", "pass") in statuses
    assert ("engine", "fail") in statuses
    assert ("system_proxy", "pass") in statuses

    settings.paths.engine_binary.parent.mkdir(parents=True, exist_ok=True)
    settings.paths.engine_binary.write_text("binary")
    settings.engine_path = settings.paths.engine_binary
    assert "pass" in {
        check["status"]
        for check in api_client.get("/api/v1/system/doctor").json()["checks"]
        if check["id"] == "engine"
    }

    now = utcnow()
    for index, days in enumerate((30, 5, -1)):
        _sql(
            settings,
            "INSERT INTO certificates "
            "(id,domain,cert_path,key_path,issuer,expires_at,auto_renew,status,"
            "source,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"cert-{index}",
                f"cert{index}.example.com",
                "/tmp/cert",
                "/tmp/key",
                "test",
                (now + timedelta(days=days)).isoformat(),
                1,
                "ready",
                "manual",
                now.isoformat(),
                now.isoformat(),
            ),
        )
    cert_checks = {
        check["id"]: check["status"]
        for check in api_client.get("/api/v1/system/doctor").json()["checks"]
        if check["id"].startswith("certificate:")
    }
    assert cert_checks["certificate:cert0.example.com"] == "pass"
    assert cert_checks["certificate:cert1.example.com"] == "warn"
    assert cert_checks["certificate:cert2.example.com"] == "fail"

    async def config() -> dict:
        return {"log": {"level": "info"}, "token": "secret", "nested": {"password": "x"}}

    api_client.app.state.services.engine.client.config = config  # type: ignore[method-assign]
    api_client.app.state.services.bus.log("info", "diagnostic log token=abc")
    diagnostics = api_client.get("/api/v1/system/diagnostics")
    assert diagnostics.status_code == 200
    body = diagnostics.json()
    assert body["version"]
    assert "[REDACTED]" in body["config"]
    assert body["logs"]

    download = api_client.get("/api/v1/system/diagnostics/download")
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment;")
    with tarfile.open(fileobj=io.BytesIO(download.content), mode="r:gz") as archive:
        member = archive.getmembers()[0]
        assert member.name == "ostium-diagnostics.json"
        assert json.loads(archive.extractfile(member).read())["version"]


def test_system_info_and_doctor_core_failures(
    api_client: TestClient, settings: Settings, fake_proxy: FakeProxy
) -> None:
    setup_admin(api_client)

    async def down() -> dict:
        raise CoreApiError(503, "down", "core_unreachable")

    api_client.app.state.services.engine.client.status = down  # type: ignore[method-assign]
    info = api_client.get("/api/v1/system/info").json()
    assert info["core"]["running"] is False
    doctor = api_client.get("/api/v1/system/doctor").json()
    assert ("core", "fail") in {(check["id"], check["status"]) for check in doctor["checks"]}

    async def bad_config() -> dict:
        raise RuntimeError("no config")

    api_client.app.state.services.engine.client.config = bad_config  # type: ignore[method-assign]
    diagnostics = api_client.get("/api/v1/system/diagnostics").json()
    assert diagnostics["config"].startswith("unavailable:")


def test_system_services_and_restart(api_client: TestClient, session_token: str) -> None:
    async def running() -> dict:
        return {"running": True}

    api_client.app.state.services.engine.client.status = running  # type: ignore[method-assign]
    services = api_client.get("/api/v1/system/services").json()["services"]
    assert services[1]["running"] is True
    assert services[1]["reachable"] is True

    async def down() -> dict:
        raise RuntimeError("unreachable")

    api_client.app.state.services.engine.client.status = down  # type: ignore[method-assign]
    services = api_client.get("/api/v1/system/services").json()["services"]
    assert services[1]["reachable"] is False

    headers = _headers(session_token)
    assert (
        api_client.post("/api/v1/system/services/nope/restart", headers=headers).status_code == 404
    )
    assert (
        api_client.post("/api/v1/system/services/ostium/restart", headers=headers).status_code
        == 409
    )

    async def reload_fail() -> dict:
        raise RuntimeError("reload failed")

    api_client.app.state.services.engine.client.reload = reload_fail  # type: ignore[method-assign]
    assert (
        api_client.post("/api/v1/system/services/ostium-core/restart", headers=headers).status_code
        == 502
    )

    async def reload() -> dict:
        return {"running": True, "revision": "r2"}

    api_client.app.state.services.engine.client.reload = reload  # type: ignore[method-assign]
    restarted = api_client.post("/api/v1/system/services/ostium-core/restart", headers=headers)
    assert restarted.status_code == 200
    assert restarted.json()["restarted"] is True


def test_preflight_reality(api_client: TestClient, monkeypatch) -> None:
    token = setup_admin(api_client)
    headers = _headers(token)

    def unavailable(*_args, **_kwargs):
        raise OSError("network down")

    monkeypatch.setattr("ostium.api.routes_system.socket.create_connection", unavailable)
    failed = api_client.post(
        "/api/v1/system/preflight/reality", params={"host": "example.com"}, headers=headers
    )
    assert failed.status_code == 200
    assert failed.json()["ok"] is False

    class TLS:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def version(self):
            return "TLSv1.3"

        def cipher(self):
            return ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)

    class Context:
        def wrap_socket(self, sock, server_hostname):
            return TLS()

    class Sock:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr("ostium.api.routes_system.socket.create_connection", lambda *a, **k: Sock())
    monkeypatch.setattr("ostium.api.routes_system.ssl.create_default_context", lambda: Context())
    ok = api_client.post("/api/v1/system/preflight/reality", headers=headers).json()
    assert ok["ok"] is True
    assert ok["tls_version"] == "TLSv1.3"

    class TLS12(TLS):
        def version(self):
            return "TLSv1.2"

    class Context12(Context):
        def wrap_socket(self, sock, server_hostname):
            return TLS12()

    monkeypatch.setattr("ostium.api.routes_system.ssl.create_default_context", lambda: Context12())
    old = api_client.post("/api/v1/system/preflight/reality", headers=headers).json()
    assert old["ok"] is False
    assert "TLS 1.3" in old["message"]


def test_server_role_rejects_client_actions(api_client: TestClient, session_token: str) -> None:
    headers = _headers(session_token)
    for path in (
        "/api/v1/system/proxy",
        "/api/v1/system/tun",
        "/api/v1/system/mode",
        "/api/v1/system/connect",
        "/api/v1/system/disconnect",
    ):
        response = api_client.post(path, json={"enabled": True, "mode": "mixed"}, headers=headers)
        assert response.status_code == 400, (path, response.text)
        assert response.json()["code"] == "role_mismatch"


def test_client_proxy_and_tun_toggles(client_api: TestClient, fake_proxy: FakeProxy) -> None:
    token = setup_admin(client_api, role="client")
    headers = _headers(token)
    services = client_api.app.state.services

    enabled = client_api.post("/api/v1/system/proxy", json={"enabled": True}, headers=headers)
    assert enabled.status_code == 200
    assert fake_proxy.enabled is True
    assert services.settings.mode.value == "system_proxy"

    disabled = client_api.post("/api/v1/system/proxy", json={"enabled": False}, headers=headers)
    assert disabled.status_code == 200
    assert fake_proxy.enabled is False
    assert services.settings.mode.value == "mixed"

    services.settings.tun_enabled = True
    conflict = client_api.post("/api/v1/system/proxy", json={"enabled": True}, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "mode_conflict"
    services.settings.tun_enabled = False

    fake_proxy.fail_enable = True
    failed = client_api.post("/api/v1/system/proxy", json={"enabled": True}, headers=headers)
    assert failed.status_code == 500
    assert failed.json()["code"] == "proxy_failed"
    fake_proxy.fail_enable = False

    fake_proxy.enabled = True
    fake_proxy.fail_disable = True
    failed_off = client_api.post("/api/v1/system/proxy", json={"enabled": False}, headers=headers)
    assert failed_off.status_code == 500
    fake_proxy.fail_disable = False
    fake_proxy.enabled = False

    async def applied(session, **kwargs) -> dict:  # type: ignore[no-untyped-def]
        return {"status": {"revision": "r1"}}

    services.engine.apply_client = applied  # type: ignore[method-assign]
    fake_proxy.enabled = True
    tun = client_api.post("/api/v1/system/tun", json={"enabled": True}, headers=headers)
    assert tun.status_code == 200
    assert tun.json()["message"] == "TUN enabled"
    assert services.settings.tun_enabled is True
    assert services.settings.mode.value == "tun"

    untun = client_api.post("/api/v1/system/tun", json={"enabled": False}, headers=headers)
    assert untun.status_code == 200
    assert services.settings.tun_enabled is False

    services.settings.allow_lan = True
    lan_tun = client_api.post("/api/v1/system/tun", json={"enabled": True}, headers=headers)
    assert lan_tun.status_code == 409
    assert lan_tun.json()["code"] == "mode_conflict"
    assert services.settings.tun_enabled is False
    services.settings.allow_lan = False

    async def fail(session, **kwargs) -> dict:  # type: ignore[no-untyped-def]
        raise EngineError("tun failed", "engine_start_failed", 500)

    services.engine.apply_client = fail  # type: ignore[method-assign]
    fake_proxy.enabled = True
    failed_tun = client_api.post("/api/v1/system/tun", json={"enabled": True}, headers=headers)
    assert failed_tun.status_code == 500
    assert services.settings.tun_enabled is False
    assert services.settings.mode.value == "mixed"
    assert fake_proxy.enabled is True

    failed_untun = client_api.post("/api/v1/system/tun", json={"enabled": False}, headers=headers)
    assert failed_untun.status_code == 500
    assert failed_untun.json()["code"] == "tun_failed"


def test_client_modes_and_connect_disconnect(client_api: TestClient, fake_proxy: FakeProxy) -> None:
    token = setup_admin(client_api, role="client")
    headers = _headers(token)
    services = client_api.app.state.services

    invalid = client_api.post("/api/v1/system/mode", json={"mode": "bogus"}, headers=headers)
    assert invalid.status_code == 400

    async def applied(session, **kwargs) -> dict:  # type: ignore[no-untyped-def]
        return {"status": {"revision": "r1"}}

    services.engine.apply_client = applied  # type: ignore[method-assign]

    tun = client_api.post("/api/v1/system/mode", json={"mode": "tun"}, headers=headers)
    assert tun.status_code == 200
    assert tun.json()["message"] == "TUN enabled"
    assert services.settings.tun_enabled is True

    mixed = client_api.post("/api/v1/system/mode", json={"mode": "mixed"}, headers=headers)
    assert mixed.status_code == 200
    assert services.settings.mode.value == "mixed"
    assert services.settings.tun_enabled is False

    sysproxy = client_api.post(
        "/api/v1/system/mode", json={"mode": "system_proxy"}, headers=headers
    )
    assert sysproxy.status_code == 200
    assert fake_proxy.enabled is True
    again = client_api.post("/api/v1/system/mode", json={"mode": "system_proxy"}, headers=headers)
    assert again.status_code == 200
    assert fake_proxy.enabled is True

    back = client_api.post("/api/v1/system/mode", json={"mode": "mixed"}, headers=headers)
    assert back.status_code == 200
    assert fake_proxy.enabled is False

    connected = client_api.post("/api/v1/system/connect", headers=headers)
    assert connected.status_code == 200
    assert connected.json()["connected"] is True

    async def fail(session, **kwargs) -> dict:  # type: ignore[no-untyped-def]
        raise EngineError("no core", "core_unreachable", 503)

    services.engine.apply_client = fail  # type: ignore[method-assign]
    rejected = client_api.post("/api/v1/system/connect", headers=headers)
    assert rejected.status_code == 503
    assert rejected.json()["code"] == "core_unreachable"

    fake_proxy.enabled = True

    async def stop_ok() -> dict:
        return {"running": False}

    services.engine.client.stop = stop_ok  # type: ignore[method-assign]
    disconnected = client_api.post("/api/v1/system/disconnect", headers=headers)
    assert disconnected.status_code == 200

    async def stop_fail() -> dict:
        raise RuntimeError("stop failed")

    services.engine.client.stop = stop_fail  # type: ignore[method-assign]
    failed = client_api.post("/api/v1/system/disconnect", headers=headers)
    assert failed.status_code == 502
    assert failed.json()["code"] == "core_error"


def test_client_settings_patch_applies(client_api: TestClient) -> None:
    token = setup_admin(client_api, role="client")
    headers = _headers(token)
    services = client_api.app.state.services

    async def applied(session, **kwargs) -> dict:  # type: ignore[no-untyped-def]
        return {"status": {"revision": "r1"}}

    services.engine.apply_client = applied  # type: ignore[method-assign]
    response = client_api.patch(
        "/api/v1/settings", json={"mixed_port": 7999, "routing_mode": "global"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["applied"] is True

    async def fail(session, **kwargs) -> dict:  # type: ignore[no-untyped-def]
        raise RuntimeError("no core")

    services.engine.apply_client = fail  # type: ignore[method-assign]
    warning = client_api.patch("/api/v1/settings", json={"log_level": "debug"}, headers=headers)
    assert warning.status_code == 200
    assert warning.json()["applied"] is False
    assert warning.json()["warning"]


def test_client_doctor_tun_checks(client_api: TestClient, monkeypatch) -> None:
    setup_admin(client_api, role="client")

    async def running() -> dict:
        return {"running": True, "pid": 1}

    client_api.app.state.services.engine.client.status = running  # type: ignore[method-assign]
    monkeypatch.setattr("ostium.api.routes_system.os.geteuid", lambda: 0)
    checks = client_api.get("/api/v1/system/doctor").json()["checks"]
    assert any(check["id"] == "tun" and check["status"] == "pass" for check in checks)

    monkeypatch.setattr("ostium.api.routes_system.os.geteuid", lambda: 1000)

    def fake_path(value):  # type: ignore[no-untyped-def]
        if str(value) == "/dev/net/tun":
            return SimpleNamespace(exists=lambda: False)
        return Path(value)

    monkeypatch.setattr("ostium.api.routes_system.Path", fake_path)
    checks = client_api.get("/api/v1/system/doctor").json()["checks"]
    assert any(check["id"] == "tun" and check["status"] == "warn" for check in checks)


def test_stats_overview_engine_connections(api_client: TestClient, session_token: str) -> None:
    services = api_client.app.state.services

    class Stats:
        def snapshot(self) -> dict:
            return {
                "online": 1,
                "rate_up": 10.0,
                "rate_down": 20.0,
                "users": [{"name": "alice"}],
            }

    async def status() -> dict:
        return {
            "running": True,
            "revision": "r1",
            "engine_version": "1.14.4",
            "started_at": "now",
        }

    async def connections() -> dict:
        return {
            "uploadTotal": 100,
            "downloadTotal": 200,
            "connections": [
                {
                    "id": "c1",
                    "metadata": {
                        "host": "example.com",
                        "destinationIP": "1.2.3.4",
                        "processPath": "/usr/bin/curl",
                    },
                },
                {"id": "c2", "metadata": {"host": "other.test"}},
            ],
        }

    services.stats = Stats()  # type: ignore[assignment]
    services.engine.client.status = status  # type: ignore[method-assign]
    services.clash.connections = connections  # type: ignore[method-assign]
    overview = api_client.get("/api/v1/stats/overview").json()
    assert overview["users"]["online"] == 1
    assert overview["traffic"]["session_up"] == 100
    assert overview["engine"]["running"] is True
    assert overview["connections"] == 2

    unfiltered = api_client.get("/api/v1/connections").json()
    assert len(unfiltered["connections"]) == 2

    filtered = api_client.get("/api/v1/connections?search=curl").json()
    assert len(filtered["connections"]) == 1
    filtered_ip = api_client.get("/api/v1/connections?search=1.2.3").json()
    assert len(filtered_ip["connections"]) == 1
    filtered_host = api_client.get("/api/v1/connections?search=other").json()
    assert len(filtered_host["connections"]) == 1

    async def close(connection_id: str) -> bool:
        return connection_id == "c1"

    services.clash.close_connection = close  # type: ignore[method-assign]
    assert (
        api_client.delete("/api/v1/connections/c1", headers=_headers(session_token)).status_code
        == 200
    )
    assert (
        api_client.delete("/api/v1/connections/c2", headers=_headers(session_token)).status_code
        == 404
    )

    async def close_all() -> bool:
        return True

    services.clash.close_all = close_all  # type: ignore[method-assign]
    assert api_client.delete("/api/v1/connections", headers=_headers(session_token)).json() == {
        "closed": True
    }

    engine = api_client.get("/api/v1/stats/engine").json()
    assert engine["running"] is True

    async def fail() -> dict:
        raise RuntimeError("down")

    services.engine.client.status = fail  # type: ignore[method-assign]
    assert api_client.get("/api/v1/stats/engine").json()["running"] is False
    fallback = api_client.get("/api/v1/stats/overview").json()
    assert fallback["engine"]["running"] is False

    metrics = api_client.get("/api/v1/metrics", headers=_headers(session_token))
    assert metrics.status_code == 200
    assert "ostium_users_total" in metrics.text
    assert "ostium_engine_running 0" in metrics.text


def test_stats_overview_without_collector(api_client: TestClient, session_token: str) -> None:
    services = api_client.app.state.services
    services.stats = None

    async def fail() -> dict:
        raise RuntimeError("down")

    async def empty() -> dict:
        return {"unavailable": True}

    services.engine.client.status = fail  # type: ignore[method-assign]
    services.clash.connections = empty  # type: ignore[method-assign]
    overview = api_client.get("/api/v1/stats/overview").json()
    assert overview["users"]["online"] == 0
    assert overview["engine"]["last_error"] == "core service is unreachable"

    metrics = api_client.get("/api/v1/metrics", headers=_headers(session_token)).text
    assert "ostium_users_online 0" in metrics


def test_traffic_series(api_client: TestClient, session_token: str, settings: Settings) -> None:
    _sql(
        settings,
        "INSERT INTO traffic_user_daily (id,user_id,day,uplink,downlink) VALUES (?,?,?,?,?)",
        ("series-1", "user-1", utcnow().date().isoformat(), 5, 6),
    )
    response = api_client.get("/api/v1/stats/traffic?days=7")
    assert response.status_code == 200
    assert response.json()["days"] == 7
    assert response.json()["series"][-1]["up"] == 5

    invalid = api_client.get("/api/v1/stats/traffic?days=0")
    assert invalid.status_code == 422


def test_logs_and_downloads(api_client: TestClient, session_token: str) -> None:
    services = api_client.app.state.services
    services.bus.log("info", "control plane ready")
    services.bus.log("warning", "quota warning token=abc")

    logs = api_client.get("/api/v1/logs?level=warning&search=quota").json()
    assert logs["source"] == "ostium"
    assert len(logs["records"]) == 1

    assert api_client.get("/api/v1/logs?source=bad").status_code == 422

    async def core_logs(limit: int) -> str:
        return "line one token=abc\nline two\nline three"

    services.engine.client.logs = core_logs  # type: ignore[method-assign]
    core = api_client.get("/api/v1/logs?source=core&limit=2&search=line").json()
    assert core["unavailable"] is False
    assert len(core["lines"]) == 2
    assert len(api_client.get("/api/v1/logs?source=core").json()["lines"]) == 3

    async def unavailable(limit: int) -> str:
        raise CoreApiError(503, "core down", "core_unreachable")

    services.engine.client.logs = unavailable  # type: ignore[method-assign]
    failed = api_client.get("/api/v1/logs?source=core").json()
    assert failed["unavailable"] is True

    download = api_client.get("/api/v1/logs/download")
    assert download.status_code == 200
    assert "[REDACTED]" in download.text or "quota" in download.text

    core_download = api_client.get("/api/v1/logs/download?source=core")
    assert core_download.status_code == 200
    assert "unavailable" in core_download.text


def test_jobs_and_alerts(api_client: TestClient, session_token: str, settings: Settings) -> None:
    headers = _headers(session_token)
    now = utcnow().isoformat()
    _sql(
        settings,
        "INSERT INTO jobs (id,type,status,progress,message,created_at,cancel_requested) "
        "VALUES (?,?,?,?,?,?,?)",
        ("job-1", "test", "queued", 0, "waiting", now, 0),
    )
    jobs = api_client.get("/api/v1/jobs?limit=9999").json()["jobs"]
    assert jobs[0]["id"] == "job-1"
    detail = api_client.get("/api/v1/jobs/job-1").json()
    assert detail["job"]["status"] == "queued"
    assert api_client.get("/api/v1/jobs/missing").status_code == 404
    cancelled = api_client.post("/api/v1/jobs/job-1/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["cancelled"] is True
    assert api_client.post("/api/v1/jobs/missing/cancel", headers=headers).status_code == 404
    assert (
        api_client.post("/api/v1/jobs/job-1/cancel", headers=headers).json()["cancelled"] is False
    )

    _sql(
        settings,
        "INSERT INTO alerts (id,level,code,message,created_at) VALUES (?,?,?,?,?)",
        ("alert-1", "warning", "test", "hello", now),
    )
    alerts = api_client.get("/api/v1/alerts").json()["alerts"]
    assert alerts[0]["id"] == "alert-1"
    assert api_client.post("/api/v1/alerts/alert-1/ack", headers=headers).status_code == 200
    assert api_client.get("/api/v1/alerts").json()["alerts"] == []
    assert api_client.get("/api/v1/alerts?include_acknowledged=true").json()["alerts"]
    assert api_client.post("/api/v1/alerts/missing/ack", headers=headers).status_code == 404


def test_websocket_events(api_client: TestClient, monkeypatch) -> None:
    with pytest.raises(WebSocketDisconnect) as excinfo:  # noqa: SIM117
        with api_client.websocket_connect("/api/v1/events"):
            pass
    assert excinfo.value.code == 4401

    setup_admin(api_client)

    async def timeout(awaitable, timeout=None):  # type: ignore[no-untyped-def]
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr("ostium.api.routes_events.asyncio.wait_for", timeout)
    with api_client.websocket_connect("/api/v1/events") as websocket:
        hello = websocket.receive_json()
        assert hello["type"] == "hello"
        ping = websocket.receive_json()
        assert ping["type"] == "ping"


def test_backup_endpoints(api_client: TestClient, session_token: str) -> None:
    headers = _headers(session_token)
    weak = api_client.post("/api/v1/backups", json={"password": "short"}, headers=headers)
    assert weak.status_code == 400

    created = api_client.post("/api/v1/backups", json={}, headers=headers)
    assert created.status_code == 202
    assert created.json()["status"] == "queued"

    assert (
        api_client.post("/api/v1/backups/missing/restore", json={}, headers=headers).status_code
        == 404
    )
    assert api_client.delete("/api/v1/backups/missing", headers=headers).status_code == 404


def test_certificate_error_paths(api_client: TestClient, session_token: str) -> None:
    headers = _headers(session_token)
    assert api_client.post("/api/v1/certificates/missing/renew", headers=headers).status_code == 404
    issued = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "self.example.com", "method": "self-signed"},
        headers=headers,
    ).json()["certificate"]
    self_signed = api_client.post(f"/api/v1/certificates/{issued['id']}/renew", headers=headers)
    assert self_signed.status_code == 400
    assert self_signed.json()["code"] == "not_acme"
    assert (
        api_client.post("/api/v1/certificates/missing/use", json={}, headers=headers).status_code
        == 404
    )
    assert api_client.delete("/api/v1/certificates/missing", headers=headers).status_code == 404

    uploaded = api_client.post(
        "/api/v1/certificates/upload",
        json={"domain": "bad.example.com", "cert_pem": "bad", "key_pem": "bad"},
        headers=headers,
    )
    assert uploaded.status_code == 400
    assert uploaded.json()["code"] == "certificate_error"


def test_acme_issue_schedules_job(api_client: TestClient, session_token: str, monkeypatch) -> None:
    headers = _headers(session_token)

    class Issuer:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def issue(self, domain: str) -> tuple[str, str]:
            raise RuntimeError("stop before network")

    monkeypatch.setattr("ostium.api.routes_certs.AcmeIssuer", Issuer)
    response = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "acme.example.com", "method": "acme"},
        headers=headers,
    )
    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["job_id"]
