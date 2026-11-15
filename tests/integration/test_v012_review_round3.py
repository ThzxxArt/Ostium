"""Third v0.1.2 review round: client artifact transfer and core hardening."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ostium.config import Role, Settings
from ostium.domain.endpoints import Endpoint, Protocol, TLSConfig
from ostium.engine.manager import EngineError, EngineManager
from ostium.engine.singbox import supervisor as supervisor_module
from ostium.engine.singbox.config import (
    CONFIG_POLICY_VERSION,
    ClientConfigSpec,
    build_client_config,
    config_digest,
)
from ostium.engine.singbox.supervisor import (
    CoreSupervisor,
    EngineCheckFailed,
)
from ostium.engine.singbox.validate import ConfigRejected
from ostium.services import enforcement as enforcement_module
from ostium.services.crypto import SecretStore
from ostium.services.events import EventBus


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _engine(path: Path) -> Path:
    return _script(
        path,
        """
if [ "$1" = "check" ]; then
  exit 0
fi
if [ "$1" = "run" ]; then
  echo "run started"
  sleep 30
  exit 0
fi
exit 1
""",
    )


def _settings(tmp_path: Path, *, role: Role = Role.CLIENT, data: str = "core") -> Settings:
    root = tmp_path / data
    value = Settings(
        role=role,
        data_dir=root,
        config_dir=root / "config",
        state_dir=root / "state",
        core_token_file=root / "runtime" / "core.token",
        engine_path=str(tmp_path / "sing-box"),
        proxy_ports=[443, 8388],
        dev=True,
    )
    value.paths.ensure()
    return value


def _client_config(tmp_path: Path, ui_dir: Path) -> tuple[dict[str, object], Path]:
    rule_set = ui_dir / "rulesets" / "ads.srs"
    rule_set.parent.mkdir(parents=True, exist_ok=True)
    rule_set.write_bytes(b"compiled-rule-set")
    endpoint = Endpoint(
        tag="node",
        protocol=Protocol.TROJAN,
        name="node",
        server="vpn.example.com",
        port=443,
        password="secret",
        tls=TLSConfig(server_name="vpn.example.com"),
    )
    spec = ClientConfigSpec(
        endpoints=[endpoint],
        mixed_port=17890,
        rule_sets=[
            {"tag": "ads", "type": "local", "format": "binary", "path": str(rule_set)},
        ],
        cache_path=str(ui_dir / "cache.db"),
        clash_secret="local-secret",
    )
    return build_client_config(spec), rule_set


def test_client_apply_rejects_paths_outside_the_core_data_dir(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.engine_path = str(_engine(tmp_path / "sing-box"))
    supervisor = CoreSupervisor(settings)
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    config, _ = _client_config(tmp_path, ui_dir)

    with pytest.raises(ConfigRejected) as excinfo:
        asyncio.run(supervisor.apply(config, config_digest(config)))
    assert excinfo.value.code == "path_not_allowed"


def test_client_apply_materialises_ui_artifacts_inside_the_core(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.engine_path = str(_engine(tmp_path / "sing-box"))
    supervisor = CoreSupervisor(settings)
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    config, rule_set = _client_config(tmp_path, ui_dir)
    artifacts = {str(rule_set): base64.b64encode(rule_set.read_bytes()).decode("ascii")}

    async def scenario() -> None:
        try:
            status = await supervisor.apply(config, config_digest(config), artifacts=artifacts)
            assert status.running is True
        finally:
            await supervisor.shutdown()

    asyncio.run(scenario())

    stored = json.loads(settings.paths.last_good_path.read_text(encoding="utf-8"))
    stored_path = stored["route"]["rule_set"][0]["path"]
    assert stored_path.startswith(str(settings.paths.data_dir))
    assert Path(stored_path).read_bytes() == b"compiled-rule-set"
    if os.name == "posix":
        assert Path(stored_path).stat().st_mode & 0o777 == 0o600
    # The cache file is disposable state owned by the core, not the UI.
    assert stored["experimental"]["cache_file"]["path"] == str(settings.paths.data_dir / "cache.db")
    # The UI-side path is never persisted into the privileged configuration.
    assert str(rule_set) not in json.dumps(stored)


def test_apply_rejects_artifact_that_the_payload_does_not_reference(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.engine_path = str(_engine(tmp_path / "sing-box"))
    supervisor = CoreSupervisor(settings)
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    config, _ = _client_config(tmp_path, ui_dir)

    with pytest.raises(EngineCheckFailed) as excinfo:
        asyncio.run(
            supervisor.apply(
                config,
                config_digest(config),
                artifacts={"/etc/passwd": base64.b64encode(b"x").decode("ascii")},
            )
        )
    assert excinfo.value.code == "artifact_rejected"


def test_manager_uploads_rule_set_bytes_and_fails_closed_when_missing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    manager = EngineManager(
        settings,
        session_factory=None,  # type: ignore[arg-type]
        store=SecretStore(settings.paths.data_dir),
        bus=EventBus(),
    )
    rule_set = tmp_path / "ui" / "rulesets" / "ads.srs"
    rule_set.parent.mkdir(parents=True)
    rule_set.write_bytes(b"payload")
    config = {
        "route": {
            "rule_set": [
                {"tag": "ads", "path": str(rule_set)},
                {"tag": "remote", "url": "https://example.com/x.srs"},
            ]
        }
    }

    artifacts = manager._client_artifacts(config)
    assert artifacts[str(rule_set)] == base64.b64encode(b"payload").decode("ascii")
    assert len(artifacts) == 1

    rule_set.unlink()
    with pytest.raises(EngineError) as excinfo:
        manager._client_artifacts(config)
    assert excinfo.value.code == "rule_set_unreadable"


def test_reload_rejects_a_stale_server_policy(tmp_path: Path) -> None:
    settings = _settings(tmp_path, role=Role.SERVER)
    settings.engine_path = str(_engine(tmp_path / "sing-box"))
    supervisor = CoreSupervisor(settings)
    settings.paths.last_good_path.write_text(
        json.dumps(
            {
                "log": {"level": "info"},
                "dns": {
                    "servers": [{"type": "udp", "tag": "local", "server": "223.5.5.5"}],
                    "final": "local",
                },
                "inbounds": [],
                "outbounds": [{"type": "direct", "tag": "direct"}],
                "route": {"rules": [], "final": "direct"},
            }
        ),
        encoding="utf-8",
    )
    settings.paths.last_good_meta_path.write_text(
        json.dumps({"policy_version": CONFIG_POLICY_VERSION - 1}), encoding="utf-8"
    )

    with pytest.raises(EngineCheckFailed) as excinfo:
        asyncio.run(supervisor.reload())
    assert excinfo.value.code == "policy_stale"


def test_start_cleans_an_orphan_before_early_returns(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, role=Role.SERVER)
    supervisor = CoreSupervisor(settings)
    called = {"value": False}

    def cleanup() -> None:
        called["value"] = True

    monkeypatch.setattr(supervisor, "_cleanup_orphan", cleanup)
    asyncio.run(supervisor.start())
    assert called["value"] is True


def test_check_timeout_kills_the_child(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    settings.engine_path = str(_engine(tmp_path / "sing-box"))
    supervisor = CoreSupervisor(settings)
    killed = {"value": False}

    class FakeProcess:
        returncode = None
        pid = 4242

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

        def kill(self) -> None:
            killed["value"] = True

        async def wait(self) -> int:
            return -9

    async def fake_exec(*args, **kwargs):  # type: ignore[no-untyped-def]
        return FakeProcess()

    async def fake_wait_for(awaitable, timeout):  # type: ignore[no-untyped-def]
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(supervisor_module.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(supervisor_module.asyncio, "wait_for", fake_wait_for)

    with pytest.raises(EngineCheckFailed):
        asyncio.run(supervisor._check(tmp_path / "config.json"))
    assert killed["value"] is True


def test_corrupt_enforcement_policy_is_fail_closed_for_the_core(tmp_path: Path) -> None:
    path = tmp_path / "enforcement.json"
    assert enforcement_module.read_enforcement(path) == set()

    path.write_text("{not json", encoding="utf-8")
    assert enforcement_module.read_enforcement(path) == set()
    with pytest.raises(enforcement_module.EnforcementError):
        enforcement_module.read_enforcement(path, strict=True)

    path.write_text(json.dumps({"version": 999, "users": []}), encoding="utf-8")
    with pytest.raises(enforcement_module.EnforcementError):
        enforcement_module.read_enforcement(path, strict=True)


def test_manual_disable_and_delete_are_persisted_for_core_restart(
    api_client: TestClient, settings: Settings, session_token: str
) -> None:
    headers = {"X-CSRF-Token": session_token}
    created = api_client.post("/api/v1/users", json={"name": "alice"}, headers=headers)
    assert created.status_code == 201, created.text
    user_id = created.json()["user"]["id"]
    path = settings.paths.enforcement_path

    disabled = api_client.patch(
        f"/api/v1/users/{user_id}", json={"enabled": False}, headers=headers
    )
    assert disabled.status_code == 200, disabled.text
    assert "alice" in json.loads(path.read_text(encoding="utf-8"))["users"]

    enabled = api_client.patch(f"/api/v1/users/{user_id}", json={"enabled": True}, headers=headers)
    assert enabled.status_code == 200, enabled.text
    assert "alice" not in json.loads(path.read_text(encoding="utf-8"))["users"]

    deleted = api_client.delete(f"/api/v1/users/{user_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert "alice" in json.loads(path.read_text(encoding="utf-8"))["users"]


def test_server_watchdog_reapplies_when_the_core_stopped() -> None:
    from ostium.api.app import _server_watchdog

    applied: list[bool] = []
    logs: list[tuple[str, str]] = []

    class Factory:
        def __call__(self) -> Factory:
            return self

        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> bool:
            return False

    class Engine:
        class Client:
            @staticmethod
            async def status() -> dict[str, object]:
                return {"running": False}

        client = Client()

        async def reconcile_server(self, session: object, *, force: bool = False) -> bool:
            applied.append(force)
            return True

    class Bus:
        @staticmethod
        def log(level: str, message: str, **kwargs: object) -> None:
            logs.append((level, message))

    services = type(
        "Services",
        (),
        {"engine": Engine(), "session_factory": Factory(), "bus": Bus()},
    )()
    ticks = {"count": 0}

    async def sleep(_: float) -> None:
        ticks["count"] += 1
        if ticks["count"] > 1:
            raise asyncio.CancelledError

    asyncio.run(_server_watchdog(services, sleep))  # type: ignore[arg-type]
    assert applied == [True]
    assert logs and logs[0][0] == "warning"


def test_uploading_a_certificate_signals_the_tls_listener(
    api_client: TestClient, settings: Settings, session_token: str
) -> None:
    from tests.integration.test_api_backups_certs import _bundle

    cert_pem, key_pem = _bundle("vpn.example.com")
    response = api_client.post(
        "/api/v1/certificates/upload",
        json={"domain": "vpn.example.com", "cert_pem": cert_pem, "key_pem": key_pem},
        headers={"X-CSRF-Token": session_token},
    )
    assert response.status_code == 200, response.text
    assert (settings.paths.runtime_dir / "reload-ui").is_file()


def test_endpoint_namespacing_avoids_generated_and_reserved_tags() -> None:
    from ostium.engine.singbox.config import namespace_endpoint_tags

    def endpoint(tag: str) -> Endpoint:
        return Endpoint(
            tag=tag,
            protocol=Protocol.TROJAN,
            name=tag,
            server="vpn.example.com",
            port=443,
            password="secret",
        )

    flattened, mapping = namespace_endpoint_tags(
        [
            ("a", "P", [endpoint("x"), endpoint("x")]),
            ("b", "Q", [endpoint("p-x"), endpoint("proxy")]),
        ]
    )
    tags = [item.tag for item in flattened]
    assert len(tags) == len(set(tags))
    assert not {"auto", "proxy", "direct"} & set(tags)
    assert "p-x" in tags
    assert mapping[("b", "p-x")] == "p-x"


def test_manager_ignores_non_path_shapes_and_rejects_oversized_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    manager = EngineManager(
        settings,
        session_factory=None,  # type: ignore[arg-type]
        store=SecretStore(settings.paths.data_dir),
        bus=EventBus(),
    )
    assert manager._client_artifacts({}) == {}
    assert manager._client_artifacts({"route": []}) == {}
    assert manager._client_artifacts({"route": {"rule_set": "nope"}}) == {}
    assert (
        manager._client_artifacts(
            {"route": {"rule_set": [1, {"path": ""}, {"url": "https://example.com/x.srs"}]}}
        )
        == {}
    )

    rule_set = tmp_path / "big.srs"
    rule_set.write_bytes(b"small")
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"x" * (16 * 1024 * 1024 + 1))
    with pytest.raises(EngineError) as excinfo:
        manager._client_artifacts({"route": {"rule_set": [{"path": str(rule_set)}]}})
    assert excinfo.value.code == "rule_set_too_large"


def test_supervisor_rejects_bad_artifacts_and_normalises_cache(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.engine_path = str(_engine(tmp_path / "sing-box"))
    supervisor = CoreSupervisor(settings)
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    config, rule_set = _client_config(tmp_path, ui_dir)
    path = str(rule_set)

    with pytest.raises(EngineCheckFailed) as excinfo:
        asyncio.run(
            supervisor.apply(
                config,
                config_digest(config),
                artifacts={f"/tmp/{index}": "eA==" for index in range(33)},
            )
        )
    assert excinfo.value.code == "artifact_rejected"

    with pytest.raises(EngineCheckFailed) as excinfo:
        asyncio.run(supervisor.apply(config, config_digest(config), artifacts={path: 1}))  # type: ignore[dict-item]
    assert excinfo.value.code == "artifact_rejected"

    with pytest.raises(EngineCheckFailed) as excinfo:
        asyncio.run(supervisor.apply(config, config_digest(config), artifacts={path: "!!!"}))
    assert excinfo.value.code == "artifact_rejected"

    oversized = base64.b64encode(b"x" * (16 * 1024 * 1024 + 1)).decode("ascii")
    with pytest.raises(EngineCheckFailed) as excinfo:
        asyncio.run(supervisor.apply(config, config_digest(config), artifacts={path: oversized}))
    assert excinfo.value.code == "artifact_too_large"

    assert supervisor._normalise_cache_path({}) == {}
    assert supervisor._normalise_cache_path({"experimental": []}) == {"experimental": []}
    assert supervisor._normalise_cache_path({"experimental": {"cache_file": "x"}}) == {
        "experimental": {"cache_file": "x"}
    }
    disabled = {"experimental": {"cache_file": {"enabled": False, "path": "/tmp/x"}}}
    assert supervisor._normalise_cache_path(disabled) == disabled
    current = {
        "experimental": {
            "cache_file": {"enabled": True, "path": str(settings.paths.data_dir / "cache.db")}
        }
    }
    assert supervisor._normalise_cache_path(current) == current
    supervisor._prune_artifacts({})


def test_reload_rejects_invalid_last_good_and_enforcement(tmp_path: Path) -> None:
    settings = _settings(tmp_path, role=Role.SERVER)
    settings.engine_path = str(_engine(tmp_path / "sing-box"))
    supervisor = CoreSupervisor(settings)
    path = settings.paths.last_good_path
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(EngineCheckFailed, match="valid JSON"):
        asyncio.run(supervisor.reload())
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(EngineCheckFailed, match="not an object"):
        asyncio.run(supervisor.reload())

    from tests.integration.test_supervisor_extended import _server_config

    path.write_text(json.dumps(_server_config()), encoding="utf-8")
    settings.paths.last_good_meta_path.write_text(
        json.dumps({"policy_version": CONFIG_POLICY_VERSION}), encoding="utf-8"
    )
    settings.paths.enforcement_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(EngineCheckFailed) as excinfo:
        asyncio.run(supervisor.reload())
    assert excinfo.value.code == "enforcement_invalid"


def test_certificate_upload_survives_a_reload_signal_failure(
    api_client: TestClient, settings: Settings, session_token: str, monkeypatch
) -> None:
    from ostium.services import certificates as cert_service
    from tests.integration.test_api_backups_certs import _bundle

    monkeypatch.setattr(cert_service, "signal_ui_reload", lambda _settings: False)
    cert_pem, key_pem = _bundle("vpn.example.com")
    response = api_client.post(
        "/api/v1/certificates/upload",
        json={"domain": "vpn.example.com", "cert_pem": cert_pem, "key_pem": key_pem},
        headers={"X-CSRF-Token": session_token},
    )
    assert response.status_code == 200, response.text


def test_certificate_upload_reports_an_apply_failure(
    api_client: TestClient, session_token: str, monkeypatch
) -> None:
    from tests.integration.test_api_backups_certs import _bundle

    services = api_client.app.state.services  # type: ignore[attr-defined]

    async def fail(_session):  # type: ignore[no-untyped-def]
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(services.engine, "apply_server", fail)
    cert_pem, key_pem = _bundle("vpn.example.com")
    response = api_client.post(
        "/api/v1/certificates/upload",
        json={"domain": "vpn.example.com", "cert_pem": cert_pem, "key_pem": key_pem},
        headers={"X-CSRF-Token": session_token},
    )
    assert response.status_code == 200, response.text
    assert response.json()["applied"] is False


def test_server_watchdog_handles_an_unreachable_core() -> None:
    from ostium.api.app import _server_watchdog

    class Factory:
        def __call__(self) -> Factory:
            return self

        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> bool:
            return False

    class Engine:
        class Client:
            @staticmethod
            async def status() -> dict[str, object]:
                raise RuntimeError("unreachable")

        client = Client()

        async def reconcile_server(self, session: object, *, force: bool = False) -> bool:
            raise AssertionError("must not apply while the core is unreachable")

    class Bus:
        @staticmethod
        def log(level: str, message: str, **kwargs: object) -> None:
            pass

    services = type(
        "Services", (), {"engine": Engine(), "session_factory": Factory(), "bus": Bus()}
    )()
    ticks = {"count": 0}

    async def sleep(_: float) -> None:
        ticks["count"] += 1
        if ticks["count"] > 1:
            raise asyncio.CancelledError

    asyncio.run(_server_watchdog(services, sleep))  # type: ignore[arg-type]


def test_enforcement_write_failure_does_not_lose_the_api_response(
    api_client: TestClient, session_token: str, monkeypatch
) -> None:
    from ostium.services import enforcement as enforcement_module

    headers = {"X-CSRF-Token": session_token}
    created = api_client.post("/api/v1/users", json={"name": "carol"}, headers=headers)
    assert created.status_code == 201, created.text
    user_id = created.json()["user"]["id"]

    def fail(_path, _names):  # type: ignore[no-untyped-def]
        raise OSError("disk full")

    monkeypatch.setattr(enforcement_module, "write_enforcement", fail)
    response = api_client.patch(
        f"/api/v1/users/{user_id}", json={"enabled": False}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["user"]["enabled"] is False


def test_bulk_delete_records_tombstones(api_client: TestClient, settings: Settings) -> None:
    from tests.conftest import csrf, setup_admin

    setup_admin(api_client)
    headers = {"X-CSRF-Token": csrf(api_client)}
    created = []
    for name in ("dave", "erin"):
        response = api_client.post("/api/v1/users", json={"name": name}, headers=headers)
        assert response.status_code == 201, response.text
        created.append(response.json()["user"]["id"])
    bulk = api_client.post(
        "/api/v1/users/bulk",
        json={"action": "delete", "ids": created},
        headers=headers,
    )
    assert bulk.status_code == 200, bulk.text
    users = json.loads(settings.paths.enforcement_path.read_text(encoding="utf-8"))["users"]
    assert {"dave", "erin"} <= set(users)


def test_server_watchdog_leaves_a_running_core_alone() -> None:
    from ostium.api.app import _server_watchdog

    class Factory:
        def __call__(self) -> Factory:
            return self

        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> bool:
            return False

    class Engine:
        class Client:
            @staticmethod
            async def status() -> dict[str, object]:
                return {"running": True}

        client = Client()

        async def reconcile_server(self, session: object, *, force: bool = False) -> bool:
            raise AssertionError("must not reapply while the core is running")

    class Bus:
        @staticmethod
        def log(level: str, message: str, **kwargs: object) -> None:
            pass

    services = type(
        "Services", (), {"engine": Engine(), "session_factory": Factory(), "bus": Bus()}
    )()
    ticks = {"count": 0}

    async def sleep(_: float) -> None:
        ticks["count"] += 1
        if ticks["count"] > 1:
            raise asyncio.CancelledError

    asyncio.run(_server_watchdog(services, sleep))  # type: ignore[arg-type]
