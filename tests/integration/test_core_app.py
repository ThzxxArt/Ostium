from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from ostium.config import Role, Settings
from ostium.core import app as core_app_module
from ostium.core.app import create_core_app, run_core
from ostium.engine.singbox.supervisor import CoreError, EngineUnavailable, SupervisorStatus


def _settings(tmp_path: Path) -> Settings:
    value = Settings(
        role=Role.SERVER,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
        engine_path=str(tmp_path / "data" / "core" / "sing-box"),
        dev=True,
    )
    value.paths.ensure()
    return value


def _status(running: bool = False) -> SupervisorStatus:
    return SupervisorStatus(
        running=running,
        pid=123 if running else None,
        revision="r1",
        config_sha256="sha",
        started_at="start",
        updated_at="update",
        last_error=None,
        log_path="/tmp/core.log",
        engine_path="/tmp/sing-box",
        engine_version="1.14.4-ostium.1",
    )


def _headers(settings: Settings) -> dict[str, str]:
    token = settings.core_token_file.read_text().strip()
    return {"Authorization": f"Bearer {token}"}


def test_core_health_auth_and_status(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_core_app(settings)
    with TestClient(app) as client:
        health = client.get("/v1/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        assert client.get("/v1/status").status_code == 401
        assert client.get("/v1/status", headers={"Authorization": "Basic x"}).status_code == 401
        assert (
            client.get("/v1/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
        )

        status = client.get("/v1/status", headers=_headers(settings))
        assert status.status_code == 200
        payload = status.json()
        assert payload["role"] == "server"
        assert payload["core_version"]
        assert payload["pid_file"].endswith("core-state.json")


def test_core_apply_role_and_validation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_core_app(settings)
    with TestClient(app) as client:
        headers = _headers(settings)
        response = client.post(
            "/v1/apply",
            json={"config": {}, "sha256": "0" * 64, "role": "client"},
            headers=headers,
        )
        assert response.status_code == 422
        assert response.json()["code"] == "role_mismatch"

        invalid = client.post(
            "/v1/apply",
            json={"config": {}, "sha256": "not-a-digest", "role": "server"},
            headers=headers,
        )
        assert invalid.status_code == 422


def test_core_reloads_approved_ports_before_apply(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.proxy_ports = [443]
    settings.save()
    app = create_core_app(settings)
    with TestClient(app) as client:
        captured: dict[str, object] = {}

        async def fake_apply(config, sha256, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return _status()

        app.state.supervisor.apply = fake_apply  # type: ignore[method-assign]
        settings.proxy_ports = [443, 9443]
        settings.save()
        response = client.post(
            "/v1/apply",
            json={"config": {}, "sha256": "0" * 64, "role": "server"},
            headers=_headers(settings),
        )
        assert response.status_code == 200
        assert captured["allowed_ports"] == {443, 9443}


def test_core_body_limits_and_content_type(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = create_core_app(settings)
    with TestClient(app) as client:
        headers = _headers(settings)
        too_large = client.post(
            "/v1/apply",
            content=b"{}",
            headers={**headers, "content-length": str(3 * 1024 * 1024)},
        )
        assert too_large.status_code == 413
        assert too_large.json()["code"] == "body_too_large"

        # A lying/short Content-Length header must still hit the body-size
        # guard after the body is read.
        actual_large = client.post(
            "/v1/apply",
            content=b"x" * (2 * 1024 * 1024 + 1),
            headers={
                **headers,
                "content-type": "application/json",
                "content-length": str(1024),
            },
        )
        assert actual_large.status_code == 413

        wrong_type = client.post(
            "/v1/apply",
            content=b"{}",
            headers={**headers, "content-type": "text/plain"},
        )
        assert wrong_type.status_code == 415

        invalid_json = client.post(
            "/v1/apply",
            content=b"{",
            headers={**headers, "content-type": "application/json"},
        )
        assert invalid_json.status_code == 422


def test_core_reload_stop_logs_config_and_errors(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    app = create_core_app(settings)
    supervisor = app.state.supervisor

    async def reload() -> SupervisorStatus:
        return _status(True)

    async def stop() -> SupervisorStatus:
        return _status(False)

    async def apply(config, sha256, **kwargs):  # type: ignore[no-untyped-def]
        raise EngineUnavailable("engine missing")

    async def unhandled(config, sha256, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    supervisor.reload = reload  # type: ignore[method-assign]
    supervisor.stop_process = stop  # type: ignore[method-assign]
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = _headers(settings)
        assert client.post("/v1/reload", headers=headers).json()["running"] is True
        assert client.post("/v1/stop", headers=headers).json()["running"] is False

        assert client.get("/v1/logs", headers=headers).status_code == 200
        assert client.get("/v1/logs?tail=0", headers=headers).status_code == 422
        assert client.get("/v1/logs?tail=9999", headers=headers).status_code == 422

        missing = client.get("/v1/config", headers=headers)
        assert missing.status_code == 404
        assert missing.json()["code"] == "not_found"

        settings.paths.last_good_path.write_text(json.dumps({"log": {"level": "info"}}))
        config = client.get("/v1/config", headers=headers)
        assert config.status_code == 200
        assert config.json()["log"]["level"] == "info"

        supervisor.apply = apply  # type: ignore[method-assign]
        error = client.post(
            "/v1/apply",
            json={
                "config": {"inbounds": [], "outbounds": []},
                "sha256": "0" * 64,
                "role": "server",
            },
            headers=headers,
        )
        assert error.status_code == 503
        assert error.json()["code"] == "engine_unavailable"

        supervisor.apply = unhandled  # type: ignore[method-assign]
        crash = client.post(
            "/v1/apply",
            json={
                "config": {"inbounds": [], "outbounds": []},
                "sha256": "0" * 64,
                "role": "server",
            },
            headers=headers,
        )
        assert crash.status_code == 500
        assert crash.json()["code"] == "internal_error"


def test_core_apply_forwards_allow_lan(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.role = Role.CLIENT
    app = create_core_app(settings)
    supervisor = app.state.supervisor
    captured: list[bool] = []

    async def apply(config, sha256, *, allow_lan=False, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(allow_lan)
        return _status(False)

    supervisor.apply = apply  # type: ignore[method-assign]
    with TestClient(app) as client:
        response = client.post(
            "/v1/apply",
            json={
                "config": {"inbounds": [], "outbounds": []},
                "sha256": "0" * 64,
                "role": "client",
                "allow_lan": True,
            },
            headers=_headers(settings),
        )
        assert response.status_code == 200
        assert captured == [True]


def test_core_lifespan_start_failure_is_reported(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.paths.last_good_path.write_text("not-json")
    app = create_core_app(settings)
    with TestClient(app) as client:
        status = client.get("/v1/status", headers=_headers(settings)).json()
        assert status["running"] is False
        assert "rejected" in (status["last_error"] or "")


def test_run_core_uvicorn_and_permissions(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    settings.core_url = ""
    captured: dict[str, object] = {}

    def fake_run(app, **kwargs) -> None:  # type: ignore[no-untyped-def]
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    run_core(settings)
    assert captured["port"] == 8788
    assert captured["host"] == "127.0.0.1"
    assert settings.core_token_file.exists()

    # A missing ostium group is tolerated.
    settings.role = Role.CLIENT
    monkeypatch.setattr("grp.getgrnam", lambda name: (_ for _ in ()).throw(KeyError(name)))
    run_core(settings)
    assert captured["port"] == 8788

    # An existing group triggers chown/chmod; failures are tolerated.
    calls: list[object] = []
    monkeypatch.setattr("grp.getgrnam", lambda name: SimpleNamespace(gr_gid=123))
    monkeypatch.setattr(core_app_module.os, "chown", lambda *args: calls.append(args))
    run_core(settings)
    assert calls
    monkeypatch.setattr(core_app_module.os, "chown", lambda *args: (_ for _ in ()).throw(OSError()))
    run_core(settings)

    # chmod failures are best-effort during startup.
    monkeypatch.setattr(
        "pathlib.Path.chmod", lambda *args, **kwargs: (_ for _ in ()).throw(OSError())
    )
    run_core(settings)


def test_core_error_handler_redacts(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    app = create_core_app(settings)
    supervisor = app.state.supervisor

    async def secret_error(config, sha256, **kwargs):  # type: ignore[no-untyped-def]
        raise CoreError("token=secret", "test_error")

    supervisor.apply = secret_error  # type: ignore[method-assign]
    with TestClient(app) as client:
        response = client.post(
            "/v1/apply",
            json={
                "config": {"inbounds": [], "outbounds": []},
                "sha256": "0" * 64,
                "role": "server",
            },
            headers=_headers(settings),
        )
        assert response.status_code == 500
        assert "secret" not in response.json()["detail"]
        assert response.json()["code"] == "test_error"
