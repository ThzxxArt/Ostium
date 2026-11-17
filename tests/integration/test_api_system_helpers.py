from __future__ import annotations

import socket
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from ostium.api import routes_system
from tests.conftest import setup_admin


def _headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


def test_lan_addresses_skips_invalid_entries(monkeypatch) -> None:
    monkeypatch.setattr(
        routes_system.psutil,
        "net_if_addrs",
        lambda: {
            "bad": [SimpleNamespace(family=socket.AF_INET, address="not-an-ip")],
            "lo": [SimpleNamespace(family=socket.AF_INET, address="127.0.0.1")],
            "lan": [SimpleNamespace(family=socket.AF_INET, address="192.168.1.5")],
        },
    )
    assert routes_system._lan_addresses() == ["192.168.1.5"]


def test_log_tail_missing_readable_and_unreadable(tmp_path: Path) -> None:
    assert routes_system._log_tail(tmp_path / "missing.log") == ""
    log = tmp_path / "ui.log"
    log.write_text("token=secret\nline2\n", encoding="utf-8")
    assert "[REDACTED]" in routes_system._log_tail(log)

    class Unreadable:
        def is_file(self) -> bool:
            return True

        def read_text(self, encoding: str = "utf-8", errors: str = "strict") -> str:
            raise OSError("denied")

    assert "unreadable" in routes_system._log_tail(Unreadable())  # type: ignore[arg-type]


def test_service_manager_state_platforms(monkeypatch) -> None:
    monkeypatch.setattr(routes_system, "os", SimpleNamespace(name="nt"))
    assert routes_system._service_manager_state()["platform"] == "scm"

    monkeypatch.setattr(routes_system, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(routes_system, "sys", SimpleNamespace(platform="darwin"))
    assert routes_system._service_manager_state()["platform"] == "launchd"

    monkeypatch.setattr(routes_system, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout="active\ninactive\n", returncode=3),
    )
    state = routes_system._service_manager_state()
    assert state["states"] == ["active", "inactive"]

    def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("no systemctl")

    monkeypatch.setattr("subprocess.run", fail)
    assert routes_system._service_manager_state()["supported"] is False


def test_dns_status_handles_invalid_metadata(api_client: TestClient, session_token: str) -> None:
    settings = api_client.app.state.services.settings
    settings.paths.last_good_meta_path.parent.mkdir(parents=True, exist_ok=True)
    settings.paths.last_good_meta_path.write_text("{not-json", encoding="utf-8")
    response = api_client.get("/api/v1/system/dns")
    assert response.status_code == 200
    assert response.json()["last_good"]["dns_mode"] is None


def test_provenance_reports_mismatch(api_client: TestClient, session_token: str) -> None:
    async def status() -> dict[str, object]:
        return {"running": True, "core_version": "0.1.0", "pid": 1}

    api_client.app.state.services.engine.client.status = status  # type: ignore[method-assign]
    payload = api_client.get("/api/v1/system/provenance").json()
    assert payload["consistency"]["ok"] is False
    assert payload["consistency"]["mismatches"][0]["surface"] == "core"


def test_diagnostics_includes_logs_and_service_manager(
    api_client: TestClient, session_token: str, tmp_path: Path
) -> None:
    services = api_client.app.state.services
    logs_dir = services.settings.paths.logs_dir
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "ui.log").write_text("token=secret\n", encoding="utf-8")
    body = api_client.get("/api/v1/system/diagnostics").json()
    assert "ui.log" in body["log_files"]
    assert "service_manager" in body
    assert "provenance" in body
    assert "dns" in body
    assert "system_proxy" in body


def test_reality_preflight_rejects_invalid_port(api_client: TestClient, session_token: str) -> None:
    response = api_client.post(
        "/api/v1/system/preflight/reality?port=0", headers=_headers(session_token)
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_toggle_proxy_reports_unreachable_core(client_api: TestClient) -> None:
    token = setup_admin(client_api, role="client")

    async def fail() -> dict[str, object]:
        raise RuntimeError("down")

    client_api.app.state.services.engine.client.status = fail  # type: ignore[method-assign]
    response = client_api.post(
        "/api/v1/system/proxy", json={"enabled": True}, headers=_headers(token)
    )
    assert response.status_code == 409
    assert response.json()["code"] == "core_not_running"


def test_connect_reports_proxy_failure(client_api: TestClient, monkeypatch) -> None:
    token = setup_admin(client_api, role="client")
    services = client_api.app.state.services
    from ostium.config import Mode

    services.settings.mode = Mode.SYSTEM_PROXY

    async def apply(session, **kwargs):  # type: ignore[no-untyped-def]
        return {"status": {"running": True, "revision": "r1"}}

    services.engine.apply_client = apply  # type: ignore[method-assign]

    def fail_enable(host: str = "127.0.0.1", port: int | None = None):  # type: ignore[no-untyped-def]
        raise RuntimeError("no proxy")

    services.proxy.enable = fail_enable  # type: ignore[method-assign]
    response = client_api.post("/api/v1/system/connect", headers=_headers(token))
    assert response.status_code == 502
    assert response.json()["code"] == "proxy_failed"


def test_toggle_proxy_persist_failure_restores_proxy(client_api: TestClient, monkeypatch) -> None:
    token = setup_admin(client_api, role="client")
    services = client_api.app.state.services

    async def running() -> dict[str, object]:
        return {"running": True, "pid": 1}

    services.engine.client.status = running  # type: ignore[method-assign]

    class Proxy:
        def __init__(self) -> None:
            self.enabled = False

        def status(self) -> dict[str, object]:
            return {"enabled": self.enabled, "supported": True, "platform": "test"}

        def enable(self, host: str = "127.0.0.1", port: int | None = None) -> dict[str, object]:
            self.enabled = True
            return self.status()

        def disable(self) -> dict[str, object]:
            self.enabled = False
            return self.status()

    services.proxy_manager = Proxy()

    def fail_save(self: object, path: object | None = None) -> Path:
        raise OSError("read-only config")

    monkeypatch.setattr(type(services.settings), "save", fail_save)
    response = client_api.post(
        "/api/v1/system/proxy", json={"enabled": True}, headers=_headers(token)
    )
    assert response.status_code == 500
    assert response.json()["code"] == "settings_write_failed"


def test_tun_enable_reports_proxy_disable_failure(client_api: TestClient) -> None:
    token = setup_admin(client_api, role="client")
    services = client_api.app.state.services
    services.settings.allow_lan = False

    def enabled() -> dict[str, object]:
        return {"enabled": True, "supported": True, "platform": "test"}

    class Proxy:
        def status(self) -> dict[str, object]:
            return enabled()

        def disable(self) -> dict[str, object]:
            raise RuntimeError("cannot disable")

    services.proxy_manager = Proxy()
    response = client_api.post(
        "/api/v1/system/tun", json={"enabled": True}, headers=_headers(token)
    )
    assert response.status_code == 500
    assert response.json()["code"] == "proxy_failed"


def test_tun_disable_apply_failure_and_save_failure(client_api: TestClient, monkeypatch) -> None:
    token = setup_admin(client_api, role="client")
    services = client_api.app.state.services
    from ostium.config import Mode

    services.settings.tun_enabled = True
    services.settings.mode = Mode.TUN

    async def fail(session, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("apply failed")

    services.engine.apply_client = fail  # type: ignore[method-assign]

    def fail_save(self: object, path: object | None = None) -> Path:
        raise OSError("read-only")

    monkeypatch.setattr(type(services.settings), "save", fail_save)
    response = client_api.post(
        "/api/v1/system/tun", json={"enabled": False}, headers=_headers(token)
    )
    assert response.status_code == 500
    assert response.json()["code"] == "tun_failed"


def test_disconnect_from_tun_survives_settings_write_failure(
    client_api: TestClient, monkeypatch
) -> None:
    token = setup_admin(client_api, role="client")
    services = client_api.app.state.services
    from ostium.config import Mode

    services.settings.mode = Mode.TUN
    services.settings.tun_enabled = True

    async def stop() -> dict[str, object]:
        return {"running": False}

    services.engine.client.stop = stop  # type: ignore[method-assign]

    def fail_save(self: object, path: object | None = None) -> Path:
        raise OSError("read-only")

    monkeypatch.setattr(type(services.settings), "save", fail_save)
    response = client_api.post("/api/v1/system/disconnect", headers=_headers(token))
    assert response.status_code == 200
    assert response.json()["connected"] is False
