"""Regression tests for the fourth v0.1.1 pre-release review round."""

from __future__ import annotations

import asyncio
import io
import socket
import tarfile
from pathlib import Path
from typing import ClassVar

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typer.testing import CliRunner

import ostium.cli.main as cli_main
from ostium.config import Role, Settings
from ostium.db.models import Certificate, ProxyUser
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.crypto import SecretStore
from ostium.services.events import EventBus
from ostium.services.netguard import UnsafeUrlError, validate_remote_url, validate_target_host
from ostium.services.stats import StatsCollector
from ostium.services.users import create_user

ROOT = Path(__file__).resolve().parents[2]


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


def test_ipv4_mapped_and_cgnat_targets_are_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    # Literal IPv6 forms of IPv4 addresses must apply the same policy as the
    # embedded IPv4 address.  Otherwise a subscription/webhook URL such as
    # ``http://[::ffff:100.100.100.200]/`` bypasses the metadata block.
    for url in (
        "http://[::ffff:100.100.100.200]/",
        "http://[::ffff:169.254.169.254]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[2002:6464:64c8::1]/",
    ):
        with pytest.raises(UnsafeUrlError):
            validate_remote_url(url, allow_private=False)
        with pytest.raises(UnsafeUrlError):
            validate_remote_url(url, allow_private=True)

    with pytest.raises(UnsafeUrlError):
        validate_target_host("::ffff:100.100.100.200", allow_private=False)
    with pytest.raises(UnsafeUrlError):
        validate_target_host("100.64.0.1", allow_private=False)
    # CGNAT is a private-egress policy, not a metadata address: a LAN client
    # may legitimately need to reach a carrier-grade-NAT subscription host.
    assert validate_remote_url("http://100.64.0.1/", allow_private=True) == "http://100.64.0.1/"

    # A public hostname must still be accepted after the normalisation change.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    assert validate_remote_url("https://example.com/x") == "https://example.com/x"


def test_long_user_name_still_produces_bounded_unique_endpoint_tags(
    api_client: TestClient, session_token: str
) -> None:
    # User names may be 64 characters, but endpoint tags are limited to 64
    # characters too.  A raw ``name + "-ss2022"`` overflows and used to make
    # user creation and the subscriptions overview return 500.
    name = "user-" + "a" * 59
    created = api_client.post("/api/v1/users", json={"name": name}, headers=_headers(session_token))
    assert created.status_code == 201, created.text
    user_id = created.json()["user"]["id"]

    exported = api_client.get(f"/api/v1/users/{user_id}/export", headers=_headers(session_token))
    assert exported.status_code == 200, exported.text
    tags = [endpoint["tag"] for endpoint in exported.json()["endpoints"]]
    assert tags
    assert all(len(tag) <= 64 for tag in tags)
    assert len(tags) == len(set(tags))

    overview = api_client.get("/api/v1/subscriptions", headers=_headers(session_token))
    assert overview.status_code == 200, overview.text


def test_certificate_files_survive_a_failed_apply_on_delete(
    api_client: TestClient, session_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "vpn.example.com", "method": "self-signed"},
        headers=_headers(session_token),
    )
    assert issued.status_code == 202, issued.text
    certificate_id = issued.json()["certificate"]["id"]

    async def _paths() -> tuple[Path, Path]:
        async with api_client.app.state.services.session_factory() as session:
            row = await session.get(Certificate, certificate_id)
            assert row is not None
            return Path(row.cert_path), Path(row.key_path)

    cert_path, key_path = asyncio.run(_paths())
    assert cert_path.is_file() and key_path.is_file()

    from ostium.engine.manager import EngineError

    async def _fail(_session: AsyncSession) -> dict[str, object]:
        raise EngineError("core is unavailable", "core_unavailable", 503)

    monkeypatch.setattr(api_client.app.state.services.engine, "apply_server", _fail)
    deleted = api_client.delete(
        f"/api/v1/certificates/{certificate_id}", headers=_headers(session_token)
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["applied"] is False
    assert "warning" in deleted.json()
    assert cert_path.is_file() and key_path.is_file()

    listed = api_client.get("/api/v1/certificates", headers=_headers(session_token))
    assert all(item["id"] != certificate_id for item in listed.json()["certificates"])


def test_fetch_rejects_https_to_http_redirect() -> None:
    from ostium.services.netguard import fetch_limited

    def _infos(*_args: object, **_kwargs: object) -> list[tuple]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    original = socket.getaddrinfo
    socket.getaddrinfo = _infos  # type: ignore[assignment]
    try:
        with respx.mock:
            respx.get("https://example.com/rules.srs").mock(
                return_value=httpx.Response(
                    302, headers={"location": "http://example.com/rules.srs"}
                )
            )
            respx.get("http://example.com/rules.srs").mock(
                return_value=httpx.Response(200, content=b"downgraded")
            )

            async def _run() -> None:
                with pytest.raises(UnsafeUrlError, match="HTTPS"):
                    await fetch_limited(
                        "https://example.com/rules.srs",
                        allow_private=False,
                        max_bytes=1024,
                    )

            asyncio.run(_run())
    finally:
        socket.getaddrinfo = original  # type: ignore[assignment]


def test_deleting_rule_set_removes_its_downloaded_file(
    api_client: TestClient, session_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    created = api_client.post(
        "/api/v1/rule-sets",
        json={"name": "cleanup", "url": "https://example.com/cleanup.srs"},
        headers=_headers(session_token),
    )
    assert created.status_code == 201, created.text
    rule_set_id = created.json()["rule_set"]["id"]
    with respx.mock:
        respx.get("https://example.com/cleanup.srs").mock(
            return_value=httpx.Response(200, content=b"rules")
        )
        updated = api_client.post(
            f"/api/v1/rule-sets/{rule_set_id}/update", headers=_headers(session_token)
        )
    assert updated.status_code == 200, updated.text
    path = Path(updated.json()["rule_set"]["path"])
    assert path.is_file()

    deleted = api_client.delete(f"/api/v1/rule-sets/{rule_set_id}", headers=_headers(session_token))
    assert deleted.status_code == 200, deleted.text
    assert not path.exists()


def test_websocket_rejection_accepts_before_closing(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from ostium.api.routes_events import events

    settings = _settings(tmp_path)
    services = SimpleNamespace(settings=settings)

    class FakeWebSocket:
        headers: ClassVar[dict[str, str]] = {"origin": "", "host": "example.com"}
        cookies: ClassVar[dict[str, str]] = {}
        client = None
        app = SimpleNamespace(state=SimpleNamespace(services=services))

        def __init__(self) -> None:
            self.order: list[object] = []

        async def accept(self) -> None:
            self.order.append("accept")

        async def close(self, code: int, reason: str = "") -> None:
            self.order.append((code, reason))

    socket = FakeWebSocket()
    asyncio.run(events(socket))  # type: ignore[arg-type]
    assert socket.order == ["accept", (4401, "authentication required")]


def test_backup_restore_bounds_archive_size_and_member_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ostium.services import backup as backup_service

    archive_path = tmp_path / "bomb.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        payload = b"x" * 128
        info = tarfile.TarInfo("ostium.db")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    monkeypatch.setattr(backup_service, "MAX_RESTORE_EXPANDED_BYTES", 8)
    with (
        tarfile.open(archive_path, "r:gz") as archive,
        pytest.raises(backup_service.BackupError, match="size limit"),
    ):
        backup_service._safe_extract(archive, tmp_path / "out")

    monkeypatch.setattr(backup_service, "MAX_ARCHIVE_MEMBERS", 0)
    with (
        tarfile.open(archive_path, "r:gz") as archive,
        pytest.raises(backup_service.BackupError, match="too many"),
    ):
        backup_service._safe_extract(archive, tmp_path / "out-many")

    settings = _settings(tmp_path)
    monkeypatch.setattr(backup_service, "MAX_BACKUP_FILE_BYTES", 8)
    with pytest.raises(backup_service.BackupError, match="too large"):
        backup_service.restore_backup(settings, archive_path)
    with pytest.raises(backup_service.BackupError, match="too large"):
        backup_service.stage_restore(settings, archive_path)


def test_ipv6_certificate_directory_is_windows_safe(tmp_path: Path) -> None:
    from ostium.services.certificates import _cert_dir

    settings = _settings(tmp_path)
    directory = _cert_dir(settings, "2001:db8::1")
    assert ":" not in directory.name
    assert directory.name == "2001_db8__1"


def test_ci_and_release_enable_branch_coverage() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "--cov-branch" in ci
    assert "--cov-branch" in release


def test_appimage_uses_appimagetool_architecture_names_and_fails_closed() -> None:
    script = (ROOT / "scripts" / "build-linux-packages.sh").read_text(encoding="utf-8")
    assert 'appimage_arch="x86_64"' in script
    assert 'appimage_arch="aarch64"' in script
    assert 'ARCH="$appimage_arch"' in script
    assert "Ostium-${VERSION}-linux-${package_arch}.AppImage" in script
    # A release job must not silently publish without the AppImage.
    assert "exit 1" in script
    assert 'echo "warning: appimagetool failed; AppImage not built" >&2\n    return' not in script


def test_docker_healthcheck_follows_port_and_tls() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "deploy" / "docker" / "docker-compose.yml").read_text(encoding="utf-8")
    for text in (dockerfile, compose):
        assert "OSTIUM_PORT:-8443" in text
        assert "https://127.0.0.1" in text
        assert "http://127.0.0.1:8443/healthz" not in text


def test_sliding_window_limiter_bounds_rotating_keys() -> None:
    from ostium.api.ratelimit import SlidingWindowLimiter

    limiter = SlidingWindowLimiter(max_window=3600.0)
    for index in range(limiter.MAX_TRACKED_KEYS + 250):
        assert limiter.allow(f"rotating:{index}", 60, 60.0) is True
    assert len(limiter._events) <= limiter.MAX_TRACKED_KEYS


def test_epoch_pending_is_kept_when_flush_commit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    store = SecretStore.from_data_dir(settings.data_dir)

    async def _run() -> None:
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                user, _password, _token = await create_user(
                    session, store, name="epoch-user", quota_bytes=0, quota_cycle="total"
                )
                user_id = user.id
                await session.commit()

            collector = StatsCollector(settings=settings, session_factory=factory, bus=EventBus())
            collector._pending[user_id].up = 10
            collector._epoch_pending[user_id] = 2
            original_commit = AsyncSession.commit

            async def failing_commit(self: AsyncSession) -> None:
                raise RuntimeError("database is locked")

            monkeypatch.setattr(AsyncSession, "commit", failing_commit)
            with pytest.raises(RuntimeError):
                await collector.flush()
            assert collector._epoch_pending == {user_id: 2}
            monkeypatch.setattr(AsyncSession, "commit", original_commit)
            await collector.flush()
            assert collector._epoch_pending == {}
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_macos_upgrade_health_check_uses_existing_ui_port() -> None:
    script = (ROOT / "deploy" / "launchd" / "install-macos.sh").read_text(encoding="utf-8")
    assert 'UI_PORT="$(sed -n' in script
    assert 'wait_for_ui "$UI_PORT"' in script
    assert "http://127.0.0.1:$port/healthz" in script


def test_cli_init_rejects_an_invalid_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    config = tmp_path / "config"
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(data))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(config))
    monkeypatch.setenv("OSTIUM_ROLE", "server")
    runner = CliRunner()
    result = runner.invoke(
        cli_main.app,
        [
            "init",
            "--role",
            "server",
            "--no-input",
            "--password",
            "verysecret123",
            "--domain",
            "not a domain",
            "--data-dir",
            str(data),
            "--config-dir",
            str(config),
            "--dev",
        ],
    )
    assert result.exit_code == 2, result.output
    assert "domain" in result.output.lower()


def test_installers_do_not_echo_a_user_supplied_admin_password() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    online = (ROOT / "scripts" / "install-online.sh").read_text(encoding="utf-8")
    for script in (install, online):
        assert "PASSWORD_GENERATED" in script
        assert "使用 --password 提供（未回显）" in script
    assert 'ADMIN_PASSWORD_DISPLAY="$ADMIN_PASSWORD"' in install
    assert 'ADMIN_PASSWORD_DISPLAY="使用 --password 提供（未回显）"' in install


def test_readme_marks_v011_as_published() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    assert "发布状态：v0.1.1 已于" in readme
    assert "尚未发布" not in readme
    assert "release status: v0.1.1 was published" in readme_en.lower()
    assert "not yet published" not in readme_en.lower()


def test_setup_overview_does_not_break_on_a_corrupt_user(
    api_client: TestClient, session_token: str
) -> None:
    # A single corrupted credential row must not take down the whole
    # subscriptions overview for every other user.
    created = api_client.post(
        "/api/v1/users", json={"name": "alice"}, headers=_headers(session_token)
    )
    assert created.status_code == 201, created.text
    disabled = api_client.patch(
        "/api/v1/inbounds/vless", json={"enabled": False}, headers=_headers(session_token)
    )
    assert disabled.status_code == 200, disabled.text

    async def _corrupt() -> None:
        async with api_client.app.state.services.session_factory() as session:
            user = (
                await session.execute(select(ProxyUser).where(ProxyUser.name == "alice"))
            ).scalar_one()
            user.ss_password_enc = "v1.not-valid-ciphertext"
            await session.commit()

    asyncio.run(_corrupt())
    overview = api_client.get("/api/v1/subscriptions", headers=_headers(session_token))
    assert overview.status_code == 200, overview.text
    assert overview.json()["subscriptions"][0]["links"] == []


def test_cli_init_domain_is_normalised_in_config_and_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    config = tmp_path / "config"
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(data))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(config))
    monkeypatch.setenv("OSTIUM_ROLE", "server")
    runner = CliRunner()
    result = runner.invoke(
        cli_main.app,
        [
            "init",
            "--role",
            "server",
            "--no-input",
            "--password",
            "verysecret123",
            "--domain",
            "VPN.Example.COM.",
            "--data-dir",
            str(data),
            "--config-dir",
            str(config),
            "--dev",
        ],
    )
    assert result.exit_code == 0, result.output

    async def _read() -> str | None:
        settings = Settings.load(config_file=config / "config.toml")
        engine = create_engine(settings.paths.db_path)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                from ostium.services.settings import get_setting

                server = await get_setting(session, "server", {})
                return server.get("domain") if isinstance(server, dict) else None
        finally:
            await engine.dispose()

    assert asyncio.run(_read()) == "vpn.example.com"
