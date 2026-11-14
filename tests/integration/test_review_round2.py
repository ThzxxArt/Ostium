"""Regression tests for the second v0.1.1 review round."""

from __future__ import annotations

import asyncio
import io
import json
import os
import plistlib
import shutil
import socket
import subprocess
import tarfile
import time
from pathlib import Path

import httpx
import pytest
import respx
import typer
from fastapi.testclient import TestClient
from sqlalchemy import select

from ostium.api import routes_events, routes_system
from ostium.config import Role, Settings
from ostium.db.models import Alert, ProxyUser, Rule, RuleSet, StatsEpoch
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.domain.endpoints import Endpoint, Protocol, TLSConfig
from ostium.engine.manager import EngineError, EngineManager
from ostium.engine.singbox.config import ClientConfigSpec, build_client_config
from ostium.engine.singbox.validate import validate_config
from ostium.services.backup import BackupError, restore_backup
from ostium.services.certificates import create_self_signed, delete_certificate
from ostium.services.crypto import SecretStore
from ostium.services.events import EventBus
from ostium.services.profiles import create_profile
from ostium.services.stats import StatsCollector
from ostium.services.users import create_user
from tests.conftest import setup_admin

ROOT = Path(__file__).resolve().parents[2]


def _headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


def test_chunked_request_body_is_bounded_before_auth(api_client: TestClient, monkeypatch) -> None:
    import ostium.api.app as app_module

    monkeypatch.setattr(app_module, "MAX_API_BODY_BYTES", 1024)

    def chunks():
        for _ in range(8):
            yield b"x" * 512

    response = api_client.post("/api/v1/auth/login", content=chunks())
    assert response.status_code == 413


def test_valid_chunked_body_still_reaches_the_handler(api_client: TestClient, monkeypatch) -> None:
    import ostium.api.app as app_module

    monkeypatch.setattr(app_module, "MAX_API_BODY_BYTES", 4096)
    body = json.dumps({"username": "admin", "password": "whatever"}).encode()

    response = api_client.post(
        "/api/v1/auth/login", content=iter([body]), headers={"content-type": "application/json"}
    )
    # The app is not initialised in this fixture; reaching the route proves the
    # middleware did not lose or double-consume the streamed body.
    assert response.status_code == 409


def test_invalid_settings_patch_does_not_mutate_live_settings(
    api_client: TestClient, session_token: str, settings: Settings
) -> None:
    headers = _headers(session_token)
    before = api_client.get("/api/v1/settings").json()["general"]["mixed_port"]
    config_before = settings.config_file.read_text(encoding="utf-8")

    response = api_client.patch(
        "/api/v1/settings",
        json={"mixed_port": 7899, "log_level": "bogus"},
        headers=headers,
    )
    assert response.status_code == 400
    after = api_client.get("/api/v1/settings").json()["general"]["mixed_port"]
    assert after == before
    assert settings.mixed_port == before
    assert "7899" not in settings.config_file.read_text(encoding="utf-8")
    assert settings.config_file.read_text(encoding="utf-8") == config_before


def test_failed_inbound_enable_does_not_widen_proxy_ports(
    api_client: TestClient, session_token: str, settings: Settings
) -> None:
    headers = _headers(session_token)
    before = list(settings.proxy_ports)
    response = api_client.patch(
        "/api/v1/inbounds/hysteria2",
        json={"port": 19443, "enabled": True},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "certificate_required"
    assert 19443 not in settings.proxy_ports
    assert settings.proxy_ports == before


def test_quota_threshold_alert_is_committed(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = Settings(
            role=Role.SERVER,
            data_dir=tmp_path / "data",
            config_dir=tmp_path / "config",
            state_dir=tmp_path / "state",
            core_token_file=tmp_path / "data" / "runtime" / "core.token",
            dev=True,
        )
        settings.paths.ensure()
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        try:
            async with factory() as session:
                user, _password, _token = await create_user(
                    session,
                    store,
                    name="near-quota",
                    quota_bytes=1000,
                    quota_cycle="total",
                )
                user.used_bytes = 850
                await session.commit()
                user_id = user.id

            collector = StatsCollector(settings=settings, session_factory=factory, bus=EventBus())
            await collector.enforce_quotas()

            async with factory() as session:
                alerts = (await session.execute(select(Alert))).scalars().all()
                stored = await session.get(ProxyUser, user_id)
            assert stored is not None and stored.enabled is True
            assert any(alert.code.startswith("quota_80") for alert in alerts)
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_rule_set_must_be_downloaded_before_client_apply(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = Settings(
            role=Role.CLIENT,
            data_dir=tmp_path / "data",
            config_dir=tmp_path / "config",
            state_dir=tmp_path / "state",
            core_token_file=tmp_path / "data" / "runtime" / "core.token",
            dev=True,
        )
        settings.paths.ensure()
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        try:
            async with factory() as session:
                endpoint = Endpoint(
                    tag="hk",
                    protocol=Protocol.VLESS_REALITY,
                    name="HK",
                    server="vpn.example.com",
                    port=443,
                    uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
                    tls=TLSConfig(reality_public_key="pub", reality_short_id="sid"),
                )
                await create_profile(session, store, name="main", endpoints=[endpoint])
                session.add(RuleSet(name="ads", url="https://example.com/ads.srs"))
                session.add(Rule(action="block", match_json={"rule_set": ["ads"]}, priority=10))
                await session.commit()

                manager = EngineManager(settings, factory, store, EventBus())
                async with factory() as session:
                    with pytest.raises(EngineError) as excinfo:
                        await manager.client_preview(session)
                assert excinfo.value.code == "rule_set_not_downloaded"
        finally:
            await engine.dispose()

    asyncio.run(_run())


@pytest.mark.integration
def test_client_core_starts_from_a_read_only_working_directory(tmp_path: Path) -> None:
    engine = os.environ.get("OSTIUM_TEST_ENGINE")
    if not engine or not Path(engine).is_file():
        pytest.skip("real sing-box binary is required")
    # This mirrors the packaged systemd/launchd clients: their working
    # directory is read-only, and sing-box used to write cache.db there.
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    endpoint = Endpoint(
        tag="hk",
        protocol=Protocol.VLESS_REALITY,
        name="HK",
        server="127.0.0.1",
        port=443,
        uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
        tls=TLSConfig(
            reality_public_key="Bs2KLXAKuw5pGFpBIwnyt896Y8mhNJHewMHHY0en6hM",
            reality_short_id="55e1651e",
        ),
    )
    (tmp_path / "data").mkdir()
    config = build_client_config(
        ClientConfigSpec(
            endpoints=[endpoint],
            mixed_port=18590,
            clash_secret="secret",
            cache_path=str(tmp_path / "data" / "cache.db"),
        )
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    readonly.chmod(0o555)
    process = subprocess.Popen(
        [engine, "run", "-c", str(config_path)],
        cwd=readonly,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        time.sleep(1.2)
        assert process.poll() is None, process.stdout.read() if process.stdout else ""
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        readonly.chmod(0o755)


def test_rule_set_304_with_missing_file_is_not_accepted(tmp_path: Path) -> None:
    from ostium.services.rules import update_rule_set

    async def _run() -> None:
        settings = Settings(
            role=Role.CLIENT,
            data_dir=tmp_path / "data",
            config_dir=tmp_path / "config",
            state_dir=tmp_path / "state",
            core_token_file=tmp_path / "data" / "runtime" / "core.token",
            dev=True,
        )
        settings.paths.ensure()
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                rule_set = RuleSet(name="ads", url="https://example.com/ads.srs", etag='"v1"')
                session.add(rule_set)
                await session.commit()
                with respx.mock:
                    respx.get("https://example.com/ads.srs").mock(return_value=httpx.Response(304))
                    result = await update_rule_set(session, settings, rule_set)
                assert result["updated"] is False
                assert "304" in str(result["error"])
                assert rule_set.last_error
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_client_cache_file_uses_an_absolute_path(tmp_path: Path) -> None:
    endpoint = Endpoint(
        tag="hk",
        protocol=Protocol.VLESS_REALITY,
        name="HK",
        server="vpn.example.com",
        port=443,
        uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
        tls=TLSConfig(reality_public_key="pub", reality_short_id="sid"),
    )
    cache = tmp_path / "cache.db"
    config = build_client_config(
        ClientConfigSpec(endpoints=[endpoint], clash_secret="s", cache_path=str(cache))
    )
    assert config["experimental"]["cache_file"]["path"] == str(cache)
    validate_config(
        config,
        role=Role.CLIENT,
        allowed_ports={7890},
        allowed_paths=[tmp_path],
    )


def test_client_units_pin_a_writable_working_directory() -> None:
    unit = (ROOT / "deploy/systemd/ostium-core-client.service").read_text(encoding="utf-8")
    assert "WorkingDirectory=/var/lib/ostium-core" in unit
    with (ROOT / "deploy/launchd/com.ostium.core.plist").open("rb") as handle:
        plist = plistlib.load(handle)
    assert plist["WorkingDirectory"] == "/Library/Application Support/Ostium"


def test_hysteria2_obfs_is_exported_in_all_formats() -> None:
    from ostium.engine.singbox.config import build_client_config
    from ostium.services.profiles import parse_subscription_text

    endpoint = Endpoint(
        tag="hy2",
        protocol=Protocol.HYSTERIA2,
        name="HY2",
        server="vpn.example.com",
        port=443,
        password="secret",
        obfs_password="obfs-secret",
        tls=TLSConfig(server_name="vpn.example.com"),
    )
    uri = endpoint.to_uri()
    assert "obfs=salamander" in uri
    assert "obfs-password=obfs-secret" in uri
    parsed = Endpoint.from_uri(uri)
    assert parsed.obfs_password == "obfs-secret"

    clash = endpoint.to_clash_proxy()
    assert clash["obfs"] == "salamander"
    assert clash["obfs-password"] == "obfs-secret"
    document = json.dumps(
        {
            "format": "ostium-profile",
            "version": 1,
            "name": "x",
            "endpoints": [endpoint.model_dump(mode="json")],
        }
    )
    assert parse_subscription_text(document)[0].obfs_password == "obfs-secret"

    outbound = endpoint.to_singbox_outbound()
    assert outbound["obfs"] == {"type": "salamander", "password": "obfs-secret"}
    config = build_client_config(
        ClientConfigSpec(endpoints=[endpoint], clash_secret="s", cache_path="/tmp/cache.db")
    )
    assert config["outbounds"][0]["obfs"]["password"] == "obfs-secret"


def test_remote_url_rejects_invalid_port() -> None:
    from ostium.services.netguard import UnsafeUrlError, validate_remote_url

    with pytest.raises(UnsafeUrlError, match="invalid port"):
        validate_remote_url("http://93.184.216.34:99999/x")


def test_preflight_reality_rejects_hostname_resolving_to_metadata(monkeypatch) -> None:
    original = socket.getaddrinfo

    def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        if host == "evil.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]
        return original(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    result = asyncio.run(routes_system.preflight_reality("evil.example", 443, None))
    assert result["ok"] is False
    assert "blocked address" in result["message"]


def test_init_force_preserves_existing_domain(tmp_path: Path, monkeypatch) -> None:
    import sqlite3

    from typer.testing import CliRunner

    from ostium.cli.main import app

    data = tmp_path / "data"
    config = tmp_path / "config"
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(data))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(config))
    monkeypatch.setenv("OSTIUM_CONFIG_FILE", str(config / "config.toml"))
    runner = CliRunner()
    first = runner.invoke(
        app,
        [
            "init",
            "--role",
            "server",
            "--no-input",
            "--password",
            "verysecret123",
            "--domain",
            "vpn.example.com",
        ],
    )
    assert first.exit_code == 0, first.output
    second = runner.invoke(
        app,
        ["init", "--role", "server", "--no-input", "--password", "verysecret123", "--force"],
    )
    assert second.exit_code == 0, second.output
    with sqlite3.connect(data / "ostium.db") as connection:
        value = connection.execute("SELECT value_json FROM settings WHERE key='server'").fetchone()[
            0
        ]
    assert json.loads(value)["domain"] == "vpn.example.com"


def test_core_install_rejects_plaintext_manifest(tmp_path: Path, monkeypatch) -> None:
    from ostium.cli.main import core_install

    monkeypatch.setenv("OSTIUM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OSTIUM_CONFIG_FILE", str(tmp_path / "config" / "config.toml"))
    with pytest.raises(typer.Exit) as excinfo:
        core_install(None, None, None, "http://example.com/core-manifest.json", None)
    assert excinfo.value.exit_code == 6


def test_system_info_reports_configured_tun_values(
    api_client: TestClient, session_token: str, settings: Settings
) -> None:
    settings.tun_mtu = 1400
    settings.tun_stack = "system"
    info = api_client.get("/api/v1/system/info", headers=_headers(session_token)).json()
    assert info["tun"]["mtu"] == 1400
    assert info["tun"]["stack"] == "system"


def test_disabling_active_profile_clears_active_id(client_api: TestClient) -> None:
    token = setup_admin(client_api, role="client")
    headers = _headers(token)
    vless = (
        "vless://2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e@vpn.example.com:443"
        "?encryption=none&security=reality&sni=www.apple.com&fp=chrome"
        "&pbk=pub&sid=55e1651e#HK"
    )
    created = client_api.post(
        "/api/v1/profiles", json={"name": "main", "text": vless}, headers=headers
    )
    assert created.status_code == 201, created.text
    profile_id = created.json()["profile"]["id"]
    assert (
        client_api.post(f"/api/v1/profiles/{profile_id}/activate", headers=headers).status_code
        == 200
    )
    disabled = client_api.patch(
        f"/api/v1/profiles/{profile_id}", json={"enabled": False}, headers=headers
    )
    assert disabled.status_code == 200
    listing = client_api.get("/api/v1/profiles").json()
    assert listing["active_profile_id"] is None


def test_acme_rejects_ip_address_domains(api_client: TestClient, session_token: str) -> None:
    response = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "203.0.113.10", "method": "acme"},
        headers=_headers(session_token),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "ip_certificate_requires_manual"


def test_tls_inbound_certificate_binding_can_be_cleared_while_disabled(
    api_client: TestClient, session_token: str
) -> None:
    headers = _headers(session_token)
    issued = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "vpn.example.com", "method": "self-signed"},
        headers=headers,
    )
    assert issued.status_code == 202, issued.text
    cleared = api_client.patch(
        "/api/v1/inbounds/hysteria2",
        json={"certificate_id": None},
        headers=headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["inbound"]["certificate"] is None
    rejected = api_client.patch(
        "/api/v1/inbounds/hysteria2",
        json={"enabled": True, "certificate_id": None},
        headers=headers,
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "certificate_required"


def test_user_note_can_be_cleared(api_client: TestClient, session_token: str) -> None:
    headers = _headers(session_token)
    created = api_client.post(
        "/api/v1/users", json={"name": "noted", "note": "hello"}, headers=headers
    ).json()["user"]
    cleared = api_client.patch(
        f"/api/v1/users/{created['id']}", json={"note": None}, headers=headers
    )
    assert cleared.status_code == 200
    assert cleared.json()["user"]["note"] == ""


def test_trojan_uri_carries_pin_and_insecure_flag() -> None:
    endpoint = Endpoint(
        tag="trojan",
        protocol=Protocol.TROJAN,
        name="Trojan",
        server="vpn.example.com",
        port=443,
        password="secret",
        tls=TLSConfig(
            server_name="vpn.example.com",
            insecure=True,
            certificate_pin_sha256="ab" * 32,
        ),
    )
    uri = endpoint.to_uri()
    assert "allowInsecure=1" in uri
    assert f"pinSHA256={'ab' * 32}" in uri
    parsed = Endpoint.from_uri(uri)
    assert parsed.tls.insecure is True
    assert parsed.tls.certificate_pin_sha256 == "ab" * 32


def test_websocket_honours_ip_allowlist(
    api_client: TestClient, settings: Settings, monkeypatch
) -> None:
    from fastapi import WebSocketDisconnect

    setup_admin(api_client)
    settings.ui_allowlist = ["203.0.113.0/24"]
    monkeypatch.setattr(routes_events, "client_ip", lambda _websocket: "198.51.100.7")
    with pytest.raises(WebSocketDisconnect) as excinfo:  # noqa: SIM117
        with api_client.websocket_connect("/api/v1/events"):
            pass
    assert excinfo.value.code == 4403
    assert "allowlisted" in excinfo.value.reason


def test_certificate_renewal_uses_a_new_file_generation(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = Settings(
            role=Role.SERVER,
            data_dir=tmp_path / "data",
            config_dir=tmp_path / "config",
            state_dir=tmp_path / "state",
            core_token_file=tmp_path / "data" / "runtime" / "core.token",
            dev=True,
        )
        settings.paths.ensure()
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                first = await create_self_signed(session, settings, domain="vpn.example.com")
                await session.commit()
                first_cert = Path(first.cert_path)
                first_key = Path(first.key_path)
                assert first_cert.is_file() and first_key.is_file()

                second = await create_self_signed(session, settings, domain="vpn.example.com")
                await session.commit()
                assert second.cert_path != str(first_cert)
                assert second.key_path != str(first_key)
                assert Path(second.cert_path).is_file()
                assert first_cert.is_file()

                await delete_certificate(session, second)
                await session.commit()
                assert not Path(second.cert_path).exists()
                assert not Path(second.key_path).exists()
                assert not first_cert.exists()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_statistics_epochs_continue_after_restart(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = Settings(
            role=Role.SERVER,
            data_dir=tmp_path / "data",
            config_dir=tmp_path / "config",
            state_dir=tmp_path / "state",
            core_token_file=tmp_path / "data" / "runtime" / "core.token",
            dev=True,
        )
        settings.paths.ensure()
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        try:
            async with factory() as session:
                user, _password, _token = await create_user(session, store, name="epoch-user")
                session.add(StatsEpoch(user_id=user.id, epoch=7))
                await session.commit()
                user_id = user.id
            collector = StatsCollector(settings=settings, session_factory=factory, bus=EventBus())
            await collector._load_epochs()
            assert collector._epochs[user_id] == 7
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_restore_rejects_invalid_manifest_json(tmp_path: Path) -> None:
    settings = Settings(
        role=Role.SERVER,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
        dev=True,
    )
    settings.paths.ensure()
    archive_path = tmp_path / "broken.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, content in {
            "manifest.json": b"{not json",
            "ostium.db": b"",
        }.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    with pytest.raises(BackupError) as excinfo:
        restore_backup(settings, archive_path)
    assert excinfo.value.code == "invalid_archive"


def test_restore_rolls_back_database_and_files_on_replacement_failure(
    tmp_path: Path, monkeypatch
) -> None:
    import sqlite3

    from ostium.services.backup import create_backup
    from ostium.services.crypto import SecretStore

    settings = Settings(
        role=Role.SERVER,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
        dev=True,
    )
    settings.paths.ensure()
    settings.save()
    SecretStore.from_data_dir(settings.data_dir)
    asyncio.run(_create_schema(settings))
    (settings.paths.certs_dir / "vpn.example.com").mkdir(parents=True)
    (settings.paths.certs_dir / "vpn.example.com" / "fullchain-test.pem").write_text("cert")
    backup = create_backup(settings, password=None)
    backup_path = settings.paths.backups_dir / backup["filename"]
    master_before = settings.paths.master_key_path.read_bytes()
    config_before = settings.config_file.read_bytes()

    with sqlite3.connect(settings.paths.db_path) as connection:
        connection.execute(
            "INSERT INTO settings(key, value_json, updated_at) "
            "VALUES ('marker', '\"live\"', '2026-01-01')"
        )
        connection.commit()

    original_copy = shutil.copy2

    def failing_copy(source, destination, *args, **kwargs):  # type: ignore[no-untyped-def]
        if "certs" in str(destination):
            raise OSError("simulated certificate copy failure")
        return original_copy(source, destination, *args, **kwargs)

    monkeypatch.setattr("ostium.services.backup.shutil.copy2", failing_copy)
    with pytest.raises(BackupError) as excinfo:
        restore_backup(settings, backup_path)
    assert excinfo.value.code == "restore_failed"
    monkeypatch.setattr("ostium.services.backup.shutil.copy2", original_copy)

    with sqlite3.connect(settings.paths.db_path) as connection:
        marker = connection.execute("SELECT value_json FROM settings WHERE key='marker'").fetchone()
    assert marker is not None
    assert settings.paths.master_key_path.read_bytes() == master_before
    assert settings.config_file.read_bytes() == config_before


async def _create_schema(settings: Settings) -> None:
    from ostium.db.session import create_engine, create_schema

    engine = create_engine(settings.paths.db_path)
    try:
        await create_schema(engine)
    finally:
        await engine.dispose()
