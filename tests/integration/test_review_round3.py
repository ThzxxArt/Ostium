"""Regression tests for the third v0.1.1 review round."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
import typer
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from typer.testing import CliRunner

import ostium.cli.main as cli_main
from ostium.config import Role, Settings
from ostium.db.models import ProxyUser
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.engine.singbox.supervisor import CoreSupervisor
from ostium.services import profiles as profile_service
from ostium.services.auth import AuthError, LoginLimiter
from ostium.services.crypto import SecretStore
from ostium.services.events import EventBus
from ostium.services.netguard import FetchedPayload
from ostium.services.profiles import ProfileError, parse_subscription_text
from ostium.services.public_url import normalize_base_url
from ostium.services.stats import StatsCollector
from ostium.services.users import create_user
from tests.conftest import setup_admin

ROOT = Path(__file__).resolve().parents[2]
VLESS = (
    "vless://2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e@vpn.example.com:443"
    "?encryption=none&security=reality&sni=www.apple.com&fp=chrome"
    "&pbk=Bs2KLXAKuw5pGFpBIwnyt896Y8mhNJHewMHHY0en6hM&sid=55e1651e#HK"
)


def _headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


def _settings(tmp_path: Path, role: Role = Role.SERVER) -> Settings:
    value = Settings(
        role=role,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
        engine_path=str(tmp_path / "data" / "core" / "sing-box"),
        dev=True,
        log_level="warning",
    )
    value.paths.ensure()
    return value


def test_linux_client_unit_rendering_does_not_double_substitute_paths(tmp_path: Path) -> None:
    script = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    start = script.index("render_unit() {")
    end = script.index("\n}\n", start) + 3
    function = script[start:end]

    source = tmp_path / "client.service"
    source.write_text(
        "[Service]\n"
        "Environment=OSTIUM_CONFIG_FILE=/etc/ostium/client.toml\n"
        "Environment=OSTIUM_DATA_DIR=/var/lib/ostium-core\n"
        "WorkingDirectory=/var/lib/ostium-core\n"
        "ReadWritePaths=/var/lib/ostium-core\n",
        encoding="utf-8",
    )
    target = tmp_path / "systemd" / "ostium-core.service"
    helper = tmp_path / "render.sh"
    helper.write_text(
        "set -euo pipefail\n"
        f"PREFIX={tmp_path / 'prefix'}\n"
        "CLIENT_DATA=/var/lib/ostium-core\n"
        "CLIENT_CONFIG=/etc/ostium/client.toml\n"
        f"{function}\n"
        f'render_unit "{source}" "{target}" "/var/lib/ostium-core" "/var/lib/ostium-core"\n',
        encoding="utf-8",
    )
    subprocess.run(["bash", str(helper)], check=True, capture_output=True, text=True)
    rendered = target.read_text(encoding="utf-8")
    assert "Environment=OSTIUM_CONFIG_FILE=/etc/ostium/client.toml\n" in rendered
    assert "/var/lib/ostium-core\n" in rendered
    assert "/var/lib/ostium-core-core" not in rendered
    assert rendered.count("/var/lib/ostium-core") == 3


def test_setup_rejects_an_invalid_domain_without_persisting_state(
    api_client: TestClient,
) -> None:
    from tests.conftest import csrf

    token = csrf(api_client)
    response = api_client.post(
        "/api/v1/setup",
        json={
            "role": "server",
            "username": "admin",
            "password": "verysecret123",
            "domain": "not a domain",
        },
        headers=_headers(token),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_domain"
    assert api_client.get("/api/v1/auth/status").json()["initialized"] is False


def test_system_info_reports_the_configured_mixed_port(
    api_client: TestClient, session_token: str, settings: Settings
) -> None:
    response = api_client.get("/api/v1/system/info", headers=_headers(session_token))
    assert response.status_code == 200
    assert response.json()["mixed_port"] == settings.mixed_port


def test_rule_set_creation_requires_https(api_client: TestClient, session_token: str) -> None:
    response = api_client.post(
        "/api/v1/rule-sets",
        json={"name": "insecure", "url": "http://example.com/rules.srs"},
        headers=_headers(session_token),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_rule_set"
    accepted = api_client.post(
        "/api/v1/rule-sets",
        json={"name": "secure", "url": "https://example.com/rules.srs"},
        headers=_headers(session_token),
    )
    assert accepted.status_code == 201


def test_corrupt_profile_export_and_test_are_controlled_errors(
    client_api: TestClient, settings: Settings
) -> None:
    token = setup_admin(client_api, role="client")
    created = client_api.post(
        "/api/v1/profiles",
        json={"name": "broken", "text": VLESS},
        headers=_headers(token),
    )
    assert created.status_code == 201
    profile_id = created.json()["profile"]["id"]

    async def _corrupt() -> None:
        from sqlalchemy import select

        from ostium.db.models import Profile

        async with client_api.app.state.services.session_factory() as session:
            profile = (
                await session.execute(select(Profile).where(Profile.id == profile_id))
            ).scalar_one()
            profile.config_enc = "v1.not-valid-ciphertext"
            await session.commit()

    asyncio.run(_corrupt())
    for path in (f"/api/v1/profiles/{profile_id}/export", f"/api/v1/profiles/{profile_id}/test"):
        response = client_api.get(path, headers=_headers(token))
        assert response.status_code == 500
        assert response.json()["code"] == "profile_corrupt"


def test_rule_set_delete_detects_list_and_legacy_string_references(
    api_client: TestClient, session_token: str
) -> None:
    headers = _headers(session_token)
    created_set = api_client.post(
        "/api/v1/rule-sets",
        json={"name": "secure", "url": "https://example.com/rules.srs"},
        headers=headers,
    )
    assert created_set.status_code == 201
    rule_set_id = created_set.json()["rule_set"]["id"]
    created_rule = api_client.post(
        "/api/v1/rules",
        json={"action": "block", "match": {"rule_set": ["secure"]}},
        headers=headers,
    )
    assert created_rule.status_code == 201
    referenced = api_client.delete(f"/api/v1/rule-sets/{rule_set_id}", headers=headers)
    assert referenced.status_code == 409
    assert referenced.json()["code"] == "rule_set_in_use"

    async def _make_legacy_reference() -> None:
        from sqlalchemy import select

        from ostium.db.models import Rule

        async with api_client.app.state.services.session_factory() as session:
            rule = (await session.execute(select(Rule))).scalar_one()
            rule.match_json = {"rule_set": "secure"}
            await session.commit()

    asyncio.run(_make_legacy_reference())
    legacy = api_client.delete(f"/api/v1/rule-sets/{rule_set_id}", headers=headers)
    assert legacy.status_code == 409


def test_profile_selected_endpoint_must_exist(client_api: TestClient, settings: Settings) -> None:
    token = setup_admin(client_api, role="client")
    created = client_api.post(
        "/api/v1/profiles",
        json={"name": "main", "text": VLESS},
        headers=_headers(token),
    )
    assert created.status_code == 201, created.text
    profile = created.json()["profile"]
    tag = profile["endpoints"][0]["tag"]
    rejected = client_api.patch(
        f"/api/v1/profiles/{profile['id']}",
        json={"selected_endpoint": "missing-tag"},
        headers=_headers(token),
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "bad_endpoint"
    accepted = client_api.patch(
        f"/api/v1/profiles/{profile['id']}",
        json={"selected_endpoint": tag},
        headers=_headers(token),
    )
    assert accepted.status_code == 200
    assert accepted.json()["profile"]["selected_endpoint"] == tag


def test_enabled_tls_inbound_cannot_be_unbound_by_certificate_patch(
    api_client: TestClient, session_token: str
) -> None:
    headers = _headers(session_token)
    issued = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "vpn.example.com", "method": "self-signed"},
        headers=headers,
    )
    assert issued.status_code == 202, issued.text
    enabled = api_client.patch(
        "/api/v1/inbounds/hysteria2",
        json={"enabled": True},
        headers=headers,
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["inbound"]["certificate"] is not None

    rejected = api_client.patch(
        "/api/v1/inbounds/hysteria2",
        json={"certificate_id": None},
        headers=headers,
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "certificate_required"
    current = api_client.get("/api/v1/inbounds").json()["inbounds"]
    hysteria = next(item for item in current if item["kind"] == "hysteria2")
    assert hysteria["certificate"] is not None

    disabled = api_client.patch(
        "/api/v1/inbounds/hysteria2",
        json={"enabled": False},
        headers=headers,
    )
    assert disabled.status_code == 200
    cleared = api_client.patch(
        "/api/v1/inbounds/hysteria2",
        json={"certificate_id": None},
        headers=headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["inbound"]["certificate"] is None


def test_login_limiter_bounds_rotating_username_keys() -> None:
    limiter = LoginLimiter()
    for index in range(limiter.MAX_TRACKED_KEYS + 250):
        limiter.fail("203.0.113.10", f"user-{index}")
    assert len(limiter.failures) <= limiter.MAX_TRACKED_KEYS
    # The most recent key still has its counter and must be rate-limited.
    for _ in range(5):
        limiter.fail("203.0.113.11", "victim")
    with pytest.raises(AuthError, match="too many failed attempts"):
        limiter.check("203.0.113.11", "victim")


def test_public_base_url_rejects_invalid_ports_and_hosts() -> None:
    with pytest.raises(ValueError):
        normalize_base_url("https://example.com:not-a-port")
    with pytest.raises(ValueError):
        normalize_base_url("https://example.com:70000")
    with pytest.raises(ValueError):
        normalize_base_url("https://:443")
    assert normalize_base_url("https://example.com/panel/") == "https://example.com/panel"


def test_clash_connection_id_is_url_encoded(tmp_path: Path) -> None:
    import httpx
    import respx

    from ostium.engine.singbox.clash_api import ClashApi

    secret = tmp_path / "clash.secret"
    secret.write_text("x", encoding="utf-8")
    api = ClashApi(secret)

    async def _run() -> None:
        with respx.mock:
            route = respx.delete("http://127.0.0.1:19090/connections/a%2Fb").mock(
                return_value=httpx.Response(204)
            )
            assert await api.close_connection("a/b") is True
            assert route.called

    asyncio.run(_run())


def test_acme_rejects_a_plaintext_directory_url(tmp_path: Path) -> None:
    from ostium.acme.client import AcmeError, AcmeIssuer
    from ostium.services.crypto import SecretStore

    settings = _settings(tmp_path)
    settings.acme_directory = "http://acme.example.com/directory"
    issuer = AcmeIssuer(settings, SecretStore.from_data_dir(settings.data_dir))
    with pytest.raises(AcmeError, match="HTTPS"):
        issuer._validated_directory_url()
    settings.acme_directory = "https://acme.example.com/directory"
    assert issuer._validated_directory_url() == "https://acme.example.com/directory"


def test_fetched_payload_falls_back_on_unknown_charset() -> None:
    payload = FetchedPayload(
        url="https://example.com/sub",
        status_code=200,
        headers={"content-type": "text/plain; charset=definitely-not-a-charset"},
        content=b"hello",
    )
    assert payload.text == "hello"


def test_subscription_yaml_alias_expansion_is_bounded() -> None:
    lines = [
        "proxies:",
        "  - &proxy {type: ss, name: first, server: 1.2.3.4, port: 8388, "
        "cipher: 2022-blake3-aes-128-gcm, password: secret}",
    ]
    lines.extend("  - *proxy" for _ in range(profile_service.MAX_YAML_ALIASES + 1))
    with pytest.raises(ProfileError, match="alias"):
        parse_subscription_text("\n".join(lines))


def test_subscription_deep_json_is_a_controlled_error() -> None:
    payload = '{"endpoints":' + "[" * 2000 + "]" * 2000 + "}"
    with pytest.raises(ProfileError):
        parse_subscription_text(payload)


def test_core_log_is_truncated_and_tailed_with_bounded_memory(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    supervisor = CoreSupervisor(settings)
    supervisor.log_path.write_bytes(b"x" * 4096 + b"\nlast line\n")
    assert supervisor.enforce_log_limit(max_bytes=1024) is True
    assert supervisor.log_path.stat().st_size < 1024

    supervisor.log_path.write_bytes(b"x" * 4096 + b"\nlast line\n")
    text = supervisor.read_logs(1, max_bytes=1024)
    assert text.strip().endswith("last line")
    assert len(text.encode()) <= 1024


def test_pending_bytes_only_reports_unflushed_counters() -> None:
    collector = StatsCollector(settings=object(), session_factory=None, bus=EventBus())  # type: ignore[arg-type]
    collector.usage["u1"] = type("Usage", (), {"up": 10_000, "down": 20_000})()
    collector._pending["u1"].up = 12
    collector._pending["u1"].down = 34
    assert collector.pending_bytes("u1") == 46
    assert collector.pending_bytes("missing") == 0


def test_stats_flush_does_not_drop_deltas_added_during_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        try:
            async with factory() as session:
                user, _password, _token = await create_user(
                    session, store, name="race", quota_bytes=0, quota_cycle="total"
                )
                await session.commit()
                user_id = user.id

            collector = StatsCollector(settings=settings, session_factory=factory, bus=EventBus())
            collector._pending[user_id].up = 100
            entered = asyncio.Event()
            release = asyncio.Event()
            original_commit = AsyncSession.commit

            async def slow_commit(self: AsyncSession) -> None:
                entered.set()
                await release.wait()
                await original_commit(self)

            monkeypatch.setattr(AsyncSession, "commit", slow_commit)
            task = asyncio.create_task(collector.flush())
            await asyncio.wait_for(entered.wait(), timeout=5)
            async with collector._pending_lock:
                collector._pending[user_id].down += 50
            release.set()
            await asyncio.wait_for(task, timeout=5)

            async with factory() as session:
                stored = await session.get(ProxyUser, user_id)
            assert stored is not None and stored.used_bytes == 100
            assert collector._pending[user_id].down == 50
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_quota_recovery_flag_survives_a_failed_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        try:
            async with factory() as session:
                user, _password, _token = await create_user(
                    session, store, name="disabled", quota_bytes=0, quota_cycle="total"
                )
                user.enabled = False
                user.disabled_reason = "quota_exceeded"
                await session.commit()

            collector = StatsCollector(settings=settings, session_factory=factory, bus=EventBus())
            original_commit = AsyncSession.commit

            async def failing_commit(self: AsyncSession) -> None:
                raise RuntimeError("database is locked")

            monkeypatch.setattr(AsyncSession, "commit", failing_commit)
            with pytest.raises(RuntimeError):
                await collector.enforce_quotas()
            assert collector._first_enforce is True
            monkeypatch.setattr(AsyncSession, "commit", original_commit)
            await collector.enforce_quotas()
            assert collector._first_enforce is False
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _init_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str = "server") -> CliRunner:
    data = tmp_path / f"{role}-data"
    config = tmp_path / f"{role}-config"
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(data))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(config))
    monkeypatch.setenv("OSTIUM_ROLE", role)
    runner = CliRunner()
    result = runner.invoke(
        cli_main.app,
        [
            "init",
            "--role",
            role,
            "--no-input",
            "--password",
            "verysecret123",
            "--data-dir",
            str(data),
            "--config-dir",
            str(config),
            "--dev",
        ],
    )
    assert result.exit_code == 0, result.output
    return runner


def test_cli_prints_one_time_token_before_an_apply_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _init_cli(tmp_path, monkeypatch)

    def fail_apply(_settings: Settings) -> None:
        raise typer.Exit(3)

    monkeypatch.setattr(cli_main, "_server_apply", fail_apply)
    created = runner.invoke(cli_main.app, ["user", "add", "alice"])
    assert created.exit_code == 3
    assert "subscription token:" in created.output

    rotated = runner.invoke(cli_main.app, ["user", "rotate", "alice", "--subscription"])
    assert rotated.exit_code == 3
    assert "new subscription token:" in rotated.output


def test_cli_open_uses_https_when_public_ui_is_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _init_cli(tmp_path, monkeypatch)
    monkeypatch.setenv("OSTIUM_PUBLIC_UI", "1")
    opened: list[str] = []
    monkeypatch.setattr(cli_main.webbrowser, "open", lambda url: opened.append(url))
    result = runner.invoke(cli_main.app, ["open"])
    assert result.exit_code == 0, result.output
    assert opened and opened[0].startswith("https://127.0.0.1:")


def test_cli_profile_commands_reject_ambiguous_names_and_clear_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _init_cli(tmp_path, monkeypatch, role="client")
    profile_file = tmp_path / "profile.txt"
    profile_file.write_text(VLESS, encoding="utf-8")
    import_args = [
        "--allow-degraded",
        "profile",
        "import",
        str(profile_file),
        "--name",
        "HK",
    ]
    assert runner.invoke(cli_main.app, import_args).exit_code == 0
    assert runner.invoke(cli_main.app, import_args).exit_code == 0
    ambiguous = runner.invoke(
        cli_main.app, ["--allow-degraded", "profile", "remove", "HK", "--yes"]
    )
    assert ambiguous.exit_code != 0
    assert "multiple" in ambiguous.output.lower()
    ambiguous_refresh = runner.invoke(
        cli_main.app, ["--allow-degraded", "profile", "refresh", "HK"]
    )
    assert ambiguous_refresh.exit_code != 0
    assert "multiple" in ambiguous_refresh.output.lower()

    # A single profile deletion must also clear the persisted active selection.
    solo_args = [
        "--allow-degraded",
        "profile",
        "import",
        str(profile_file),
        "--name",
        "Solo",
    ]
    assert runner.invoke(cli_main.app, solo_args).exit_code == 0

    async def _activate() -> str:
        data = tmp_path / "client-data"
        config = tmp_path / "client-config"
        settings = Settings.load(
            config_file=config / "config.toml",
        )
        settings.data_dir = data
        settings.state_dir = data / "state"
        settings.paths.ensure()
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        try:
            from sqlalchemy import select

            from ostium.db.models import Profile
            from ostium.services.settings import get_setting, set_setting

            async with factory() as session:
                profile = (
                    await session.execute(select(Profile).where(Profile.name == "Solo"))
                ).scalar_one()
                await set_setting(session, "active_profile_id", profile.id)
                await session.commit()
                value = await get_setting(session, "active_profile_id")
                assert value == profile.id
                return profile.id
        finally:
            await engine.dispose()

    profile_id = asyncio.run(_activate())
    removed = runner.invoke(
        cli_main.app, ["--allow-degraded", "profile", "remove", "Solo", "--yes"]
    )
    assert removed.exit_code == 0, removed.output

    async def _active() -> object:
        data = tmp_path / "client-data"
        config = tmp_path / "client-config"
        settings = Settings.load(config_file=config / "config.toml")
        settings.data_dir = data
        settings.state_dir = data / "state"
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        try:
            from ostium.services.settings import get_setting

            async with factory() as session:
                return await get_setting(session, "active_profile_id")
        finally:
            await engine.dispose()

    assert asyncio.run(_active()) is None
    assert profile_id
