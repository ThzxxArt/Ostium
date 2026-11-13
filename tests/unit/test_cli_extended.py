from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx
from typer.testing import CliRunner

from ostium.cli import main as cli
from ostium.cli.main import app
from ostium.config import Settings

VLESS = (
    "vless://2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e@vpn.example.com:443"
    "?encryption=none&security=reality&sni=www.apple.com&fp=chrome"
    "&pbk=pub&sid=55e1651e#HK"
)


def _init(
    tmp_path: Path, monkeypatch, role: str = "server", password: str = "verysecret123"
) -> CliRunner:
    data = tmp_path / "data"
    config = tmp_path / "config"
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(data))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(config))
    monkeypatch.setenv("OSTIUM_ROLE", role)
    runner = CliRunner()
    args = [
        "init",
        "--role",
        role,
        "--no-input",
        "--data-dir",
        str(data),
        "--config-dir",
        str(config),
        "--dev",
    ]
    if password:
        args += ["--password", password]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return runner


def test_init_generated_password_force_and_invalid_role(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "generated-data"
    config = tmp_path / "generated-config"
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(data))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(config))
    monkeypatch.setenv("OSTIUM_ROLE", "server")
    runner = CliRunner()
    generated = runner.invoke(
        app,
        [
            "init",
            "--role",
            "server",
            "--no-input",
            "--data-dir",
            str(data),
            "--config-dir",
            str(config),
            "--dev",
        ],
    )
    assert generated.exit_code == 0, generated.output
    assert "Generated administrator password" in generated.output

    # Re-running is idempotent unless --force is given.
    second = runner.invoke(app, ["init", "--role", "server", "--no-input"])
    assert second.exit_code == 0
    forced = runner.invoke(
        app,
        ["init", "--role", "server", "--no-input", "--password", "newsecret123", "--force"],
    )
    assert forced.exit_code == 0, forced.output
    assert "initialised" in forced.output

    invalid = runner.invoke(app, ["init", "--role", "nonsense", "--no-input"])
    assert invalid.exit_code == 2


def test_init_custom_ui_host_and_port(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "proxy-data"
    config = tmp_path / "proxy-config"
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(data))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(config))
    monkeypatch.setenv("OSTIUM_ROLE", "server")
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "init",
            "--role",
            "server",
            "--no-input",
            "--host",
            "127.0.0.1",
            "--port",
            "9443",
            "--password",
            "verysecret123",
        ],
    )
    assert result.exit_code == 0, result.output
    settings = Settings.load()
    assert settings.host == "127.0.0.1"
    assert settings.port == 9443


def test_status_open_and_connect_commands(tmp_path: Path, monkeypatch) -> None:
    runner = _init(tmp_path, monkeypatch)

    monkeypatch.setattr(
        cli,
        "_api",
        lambda settings, method, path, **kwargs: {
            "services": [{}, {"running": True, "reachable": True}]
        },
    )
    status = runner.invoke(app, ["status", "--json"])
    assert status.exit_code == 0
    assert '"running": true' in status.output

    monkeypatch.setattr(cli, "_api", lambda *a, **k: (_ for _ in ()).throw(SystemExit(4)))
    offline = runner.invoke(app, ["status"])
    assert offline.exit_code == 0
    assert "stopped" in offline.output

    opened: list[str] = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url))
    assert runner.invoke(app, ["open"]).exit_code == 0
    assert "local-login?token=" in opened[0]

    calls: list[tuple[str, str]] = []

    def api(settings, method, path, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((method, path))
        return {"ok": True}

    monkeypatch.setattr(cli, "_api", api)
    assert runner.invoke(app, ["connect"]).exit_code == 0
    assert runner.invoke(app, ["disconnect"]).exit_code == 0
    assert calls == [("POST", "/api/v1/system/connect"), ("POST", "/api/v1/system/disconnect")]


def test_proxy_tun_and_update_commands(tmp_path: Path, monkeypatch) -> None:
    runner = _init(tmp_path, monkeypatch)

    class Proxy:
        def enable(self, host, port):  # type: ignore[no-untyped-def]
            return {"enabled": True}

        def disable(self):  # type: ignore[no-untyped-def]
            return {"enabled": False}

        def status(self):  # type: ignore[no-untyped-def]
            return {"enabled": False}

    monkeypatch.setattr("ostium.system.proxy.system_proxy", lambda settings: Proxy())
    assert runner.invoke(app, ["proxy", "on"]).exit_code == 0
    assert runner.invoke(app, ["proxy", "off"]).exit_code == 0
    assert runner.invoke(app, ["proxy", "status"]).exit_code == 0

    class Failing(Proxy):
        def enable(self, host, port):  # type: ignore[no-untyped-def]
            raise __import__("ostium.system.proxy", fromlist=["ProxyError"]).ProxyError("no")

    monkeypatch.setattr("ostium.system.proxy.system_proxy", lambda settings: Failing())
    assert runner.invoke(app, ["proxy", "on"]).exit_code == 5

    monkeypatch.setattr(cli, "_api", lambda *a, **k: {"mode": "tun"})
    assert runner.invoke(app, ["tun", "status"]).exit_code == 0
    assert runner.invoke(app, ["tun", "on"]).exit_code == 0
    assert runner.invoke(app, ["tun", "off"]).exit_code == 0
    assert runner.invoke(app, ["tun", "bad"]).exit_code == 2
    assert runner.invoke(app, ["update"]).exit_code == 0
    assert "Automatic updates are disabled" in runner.invoke(app, ["update"]).output


def test_logs_and_doctor(tmp_path: Path, monkeypatch) -> None:
    runner = _init(tmp_path, monkeypatch)
    logs = tmp_path / "data" / "logs" / "ostium.log"
    logs.parent.mkdir(parents=True, exist_ok=True)
    logs.write_text("line1\nline2\n")

    assert runner.invoke(app, ["logs"]).exit_code == 0
    assert "line2" in runner.invoke(app, ["logs"]).output

    monkeypatch.setattr("ostium.cli.main.shutil.which", lambda name: None)
    logs.unlink()
    assert runner.invoke(app, ["logs"]).exit_code == 4

    # Follow mode stops cleanly on Ctrl-C.
    logs.write_text("line\n")
    monkeypatch.setattr("time.sleep", lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert runner.invoke(app, ["logs", "--follow"]).exit_code == 0

    monkeypatch.setattr(
        cli.httpx,
        "get",
        lambda *a, **k: SimpleNamespace(json=lambda: {"status": "ok"}),
    )
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1  # core binary is absent in the data dir
    parsed = json.loads(result.output[result.output.index("{") :])
    assert any(check["id"] == "core_api" for check in parsed["checks"])

    engine = tmp_path / "data" / "core" / "sing-box"
    engine.parent.mkdir(parents=True, exist_ok=True)
    engine.write_text("binary")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0

    monkeypatch.setattr(
        cli.httpx,
        "get",
        lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1


def test_diagnostics_and_service_commands(tmp_path: Path, monkeypatch) -> None:
    runner = _init(tmp_path, monkeypatch)
    output = tmp_path / "diag.tar.gz"
    assert runner.invoke(app, ["diagnostics", "export", "--output", str(output)]).exit_code == 0
    with tarfile.open(output) as archive:
        assert archive.getnames() == ["ostium-diagnostics.json"]
    assert runner.invoke(app, ["diagnostics", "bad"]).exit_code == 2

    monkeypatch.setattr(cli.sys, "platform", "darwin")
    assert runner.invoke(app, ["service", "install"]).exit_code == 5
    assert runner.invoke(app, ["service", "uninstall"]).exit_code == 5

    monkeypatch.setattr(cli.sys, "platform", "linux")
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000)
    assert runner.invoke(app, ["service", "install"]).exit_code == 5
    assert runner.invoke(app, ["service", "uninstall"]).exit_code == 5

    calls: list[str] = []
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(cli.shutil, "copy2", lambda *a, **k: calls.append("copy"))
    monkeypatch.setattr(cli.os, "system", lambda command: calls.append(command))
    assert runner.invoke(app, ["service", "install"]).exit_code == 0
    assert calls


def test_core_commands(tmp_path: Path, monkeypatch) -> None:
    runner = _init(tmp_path, monkeypatch)

    original_get = cli.httpx.get
    monkeypatch.setattr(
        cli.httpx,
        "get",
        lambda *a, **k: SimpleNamespace(json=lambda: {"status": "ok"}),
    )
    assert runner.invoke(app, ["core", "status"]).exit_code == 0
    monkeypatch.setattr(
        cli.httpx,
        "get",
        lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )
    assert runner.invoke(app, ["core", "status"]).exit_code == 4
    monkeypatch.setattr(cli.httpx, "get", original_get)

    assert runner.invoke(app, ["core", "version"]).exit_code == 6
    target = tmp_path / "data" / "core" / "sing-box"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("binary")
    monkeypatch.setattr(
        "subprocess.run", lambda *a, **k: SimpleNamespace(stdout="1.14.4", stderr="")
    )
    assert runner.invoke(app, ["core", "version"]).exit_code == 0

    source = tmp_path / "source-sing-box"
    source.write_text("new binary")
    assert runner.invoke(app, ["core", "install", "--binary", str(source)]).exit_code == 0
    assert target.read_text() == "new binary"

    with respx.mock:
        respx.get("https://example.com/core").mock(
            return_value=httpx.Response(200, content=b"url binary")
        )
        assert (
            runner.invoke(app, ["core", "install", "--url", "https://example.com/core"]).exit_code
            == 2
        )
        assert target.read_text() == "new binary"

        import hashlib

        digest = hashlib.sha256(b"url binary").hexdigest()
        assert (
            runner.invoke(
                app,
                [
                    "core",
                    "install",
                    "--url",
                    "https://example.com/core",
                    "--sha256",
                    digest,
                ],
            ).exit_code
            == 0
        )
        assert target.read_bytes() == b"url binary"

        archive_buffer = io.BytesIO()
        with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
            info = tarfile.TarInfo("sing-box")
            info.size = len(b"archive binary")
            archive.addfile(info, io.BytesIO(b"archive binary"))
        archive_bytes = archive_buffer.getvalue()
        respx.get("https://example.com/core.tar.gz").mock(
            return_value=httpx.Response(200, content=archive_bytes)
        )
        assert (
            runner.invoke(
                app,
                [
                    "core",
                    "install",
                    "--url",
                    "https://example.com/core.tar.gz",
                    "--sha256",
                    hashlib.sha256(archive_bytes).hexdigest(),
                ],
            ).exit_code
            == 0
        )
        assert target.read_bytes() == b"archive binary"

    with respx.mock:
        respx.get("https://example.com/core").mock(return_value=httpx.Response(200, content=b"x"))
        assert (
            runner.invoke(
                app,
                ["core", "install", "--url", "https://example.com/core", "--sha256", "0" * 64],
            ).exit_code
            == 6
        )
    assert runner.invoke(app, ["core", "install"]).exit_code == 2


def test_core_manifest_install(tmp_path: Path, monkeypatch) -> None:
    runner = _init(tmp_path, monkeypatch)

    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        data = b"manifest binary"
        info = tarfile.TarInfo("sing-box")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    content = archive.getvalue()
    import hashlib

    manifest = {
        "artifacts": [
            {
                "os": "linux",
                "arch": "amd64",
                "version": "1.14.4",
                "url": "https://example.com/core.tar.gz",
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cli.platform, "machine", lambda: "x86_64")

    with respx.mock:
        respx.get("https://example.com/core.tar.gz").mock(
            return_value=httpx.Response(200, content=content)
        )
        result = runner.invoke(app, ["core", "install", "--manifest", str(manifest_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "data" / "core" / "sing-box").read_bytes() == b"manifest binary"

    empty_manifest = tmp_path / "empty.json"
    empty_manifest.write_text('{"artifacts": []}')
    assert runner.invoke(app, ["core", "install", "--manifest", str(empty_manifest)]).exit_code == 6

    bad_manifest = tmp_path / "bad.json"
    bad_manifest.write_text("{")
    assert runner.invoke(app, ["core", "install", "--manifest", str(bad_manifest)]).exit_code == 6

    with respx.mock:
        respx.get("https://example.com/core.tar.gz").mock(
            return_value=httpx.Response(200, content=b"x")
        )
        mismatch = runner.invoke(app, ["core", "install", "--manifest", str(manifest_path)])
    assert mismatch.exit_code == 6

    recorded: list[tuple] = []
    monkeypatch.setattr(cli, "core_install", lambda *args: recorded.append(args))
    assert runner.invoke(app, ["core", "update", "--version", "1.14.4"]).exit_code == 0
    assert recorded and recorded[0][4] == "1.14.4"


def test_user_command_errors_and_rotation(tmp_path: Path, monkeypatch) -> None:
    runner = _init(tmp_path, monkeypatch)
    assert runner.invoke(app, ["user", "add", "alice", "--quota", "1G"]).exit_code == 0
    assert runner.invoke(app, ["user", "add", "alice"]).exit_code == 1  # constraint violation
    assert runner.invoke(app, ["user", "show", "missing"]).exit_code == 1
    assert runner.invoke(app, ["user", "disable", "missing"]).exit_code == 1
    assert runner.invoke(app, ["user", "rotate", "alice", "--subscription"]).exit_code == 0
    assert runner.invoke(app, ["user", "subscription", "alice", "--rotate"]).exit_code == 0
    assert runner.invoke(app, ["user", "export", "missing"]).exit_code == 1
    assert runner.invoke(app, ["user", "quota", "alice", "--quota", "2M"]).exit_code == 0

    # Declining the destructive confirmation aborts with a non-zero exit.
    assert runner.invoke(app, ["user", "remove", "alice"], input="n\n").exit_code == 1
    assert runner.invoke(app, ["user", "remove", "alice", "--yes"]).exit_code == 0


def test_profile_url_import_refresh_and_errors(tmp_path: Path, monkeypatch) -> None:
    runner = _init(tmp_path, monkeypatch, role="client")
    with respx.mock:
        respx.get("https://sub.example.com/list").mock(return_value=httpx.Response(200, text=VLESS))
        respx.post("http://127.0.0.1:8788/v1/apply").mock(
            return_value=httpx.Response(200, json={"running": True})
        )
        imported = runner.invoke(
            app, ["profile", "import", "https://sub.example.com/list", "--name", "HK"]
        )
    assert imported.exit_code == 0, imported.output
    assert runner.invoke(app, ["profile", "list", "--json"]).exit_code == 0

    with respx.mock:
        respx.get("https://sub.example.com/list").mock(return_value=httpx.Response(200, text=VLESS))
        respx.post("http://127.0.0.1:8788/v1/apply").mock(
            return_value=httpx.Response(200, json={"running": True})
        )
        assert runner.invoke(app, ["profile", "refresh", "HK"]).exit_code == 0

    assert runner.invoke(app, ["profile", "refresh", "missing"]).exit_code == 1
    assert runner.invoke(app, ["profile", "remove", "missing", "--yes"]).exit_code == 1
    assert runner.invoke(app, ["profile", "remove", "HK"], input="n\n").exit_code == 1

    literal = runner.invoke(app, ["profile", "import", VLESS, "--name", "literal"])
    assert literal.exit_code == 0
    assert runner.invoke(app, ["profile", "remove", "HK", "--yes"]).exit_code == 0
    assert runner.invoke(app, ["profile", "remove", "literal", "--yes"]).exit_code == 0

    with respx.mock:
        respx.get("https://sub.example.com/list").mock(return_value=httpx.Response(500))
        failed = runner.invoke(
            app, ["profile", "import", "https://sub.example.com/list", "--name", "bad"]
        )
    assert failed.exit_code == 1


def test_cert_backup_and_serve_commands(tmp_path: Path, monkeypatch) -> None:
    runner = _init(tmp_path, monkeypatch)
    assert runner.invoke(app, ["cert", "issue", "cert.example.com"]).exit_code == 2
    assert runner.invoke(app, ["cert", "issue", "cert.example.com", "--self-signed"]).exit_code == 0
    assert runner.invoke(app, ["cert", "list"]).exit_code == 0

    created = runner.invoke(app, ["backup", "create"])
    assert created.exit_code == 0
    assert runner.invoke(app, ["backup", "list"]).exit_code == 0

    backup_path = next((tmp_path / "data" / "backups").glob("ostium-backup-*"))
    restored = runner.invoke(app, ["backup", "restore", str(backup_path), "--yes"])
    assert restored.exit_code == 0
    assert runner.invoke(app, ["backup", "restore", str(backup_path)], input="n\n").exit_code == 1

    recorded: dict[str, object] = {}

    def fake_run(app_obj, **kwargs):  # type: ignore[no-untyped-def]
        recorded["app"] = app_obj
        recorded.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    served = runner.invoke(app, ["serve", "--host", "127.0.0.1", "--port", "18445"])
    assert served.exit_code == 0, served.output
    assert recorded["host"] == "127.0.0.1"
    assert recorded["port"] == 18445

    # Public UI without a ready certificate refuses to start.  Use a fresh
    # data directory so no restored certificate is present.
    from ostium.config import Settings

    fresh_data = tmp_path / "fresh-data"
    fresh_config = tmp_path / "fresh-config"
    fresh_state = tmp_path / "fresh-state"
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(fresh_data))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(fresh_config))
    monkeypatch.setenv("OSTIUM_STATE_DIR", str(fresh_state))
    monkeypatch.setenv("OSTIUM_ROLE", "server")
    assert (
        runner.invoke(
            app,
            [
                "init",
                "--role",
                "server",
                "--no-input",
                "--password",
                "verysecret123",
                "--data-dir",
                str(fresh_data),
                "--config-dir",
                str(fresh_config),
                "--dev",
            ],
        ).exit_code
        == 0
    )
    settings = Settings.load()
    settings.public_ui = True
    settings.save()
    refused = runner.invoke(app, ["serve"])
    assert refused.exit_code == 6


def test_serve_uses_only_unexpired_ready_certificates(tmp_path: Path, monkeypatch) -> None:
    import asyncio
    from datetime import timedelta

    from ostium.db.models import Certificate
    from ostium.db.session import create_engine, create_session_factory
    from ostium.util.time import utcnow

    runner = _init(tmp_path, monkeypatch)
    settings = Settings.load()
    settings.public_ui = True
    settings.save()
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_text("cert")
    key_path.write_text("key")

    async def enable_totp() -> None:
        from ostium.services.auth import get_admin

        engine = create_engine(settings.paths.db_path)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                admin = await get_admin(session)
                assert admin is not None
                admin.totp_secret_enc = "configured"
                await session.commit()
        finally:
            await engine.dispose()

    async def add_certificate(expires_at) -> None:  # type: ignore[no-untyped-def]
        engine = create_engine(settings.paths.db_path)
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                from sqlalchemy import delete

                await session.execute(delete(Certificate))
                session.add(
                    Certificate(
                        domain="vpn.example.com",
                        cert_path=str(cert_path),
                        key_path=str(key_path),
                        expires_at=expires_at,
                        status="ready",
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    recorded: dict[str, object] = {}

    def fake_run(_app, **kwargs):  # type: ignore[no-untyped-def]
        recorded.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    asyncio.run(enable_totp())
    asyncio.run(add_certificate(utcnow() + timedelta(days=30)))
    served = runner.invoke(app, ["serve"])
    assert served.exit_code == 0, served.output
    assert recorded["ssl_certfile"] == str(cert_path)
    assert recorded["ssl_keyfile"] == str(key_path)

    asyncio.run(add_certificate(utcnow() - timedelta(days=1)))
    expired = runner.invoke(app, ["serve"])
    assert expired.exit_code == 6


def test_core_run_delegates(tmp_path: Path, monkeypatch) -> None:
    runner = _init(tmp_path, monkeypatch)
    called: list[object] = []
    monkeypatch.setattr("ostium.core.app.run_core", lambda settings: called.append(settings))
    assert runner.invoke(app, ["core-run"]).exit_code == 0
    assert called


def test_api_helper_paths(tmp_path: Path, monkeypatch) -> None:
    from ostium.config import Settings

    data = tmp_path / "api-data"
    config = tmp_path / "api-config"
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(data))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(config))
    monkeypatch.setenv("OSTIUM_CONFIG_FILE", str(config / "config.toml"))
    settings = Settings(
        data_dir=data,
        config_dir=config,
        state_dir=tmp_path / "api-state",
        core_token_file=data / "runtime" / "core.token",
    )
    settings.paths.ensure()

    import typer

    with pytest.raises(typer.Exit) as missing:
        cli._api(settings, "GET", "/x")
    assert missing.value.exit_code == 4

    token_path = settings.paths.runtime_dir / "cli.token"
    token_path.write_text("token")

    def response(status: int, payload=None, text: str = "", content: bytes | None = None):  # type: ignore[no-untyped-def]
        body = json.dumps(payload).encode() if payload is not None else (content or text.encode())
        return SimpleNamespace(
            status_code=status,
            content=body,
            text=text or body.decode(),
            json=lambda: payload if payload is not None else (_ for _ in ()).throw(ValueError()),
        )

    monkeypatch.setattr(cli.httpx, "request", lambda *a, **k: response(200, {"ok": True}))
    assert cli._api(settings, "GET", "/x") == {"ok": True}
    monkeypatch.setattr(cli.httpx, "request", lambda *a, **k: response(200, content=b""))
    assert cli._api(settings, "GET", "/x") == {}
    monkeypatch.setattr(
        cli.httpx, "request", lambda *a, **k: response(400, {"detail": "bad request"})
    )
    with pytest.raises(typer.Exit) as error:
        cli._api(settings, "GET", "/x")
    assert error.value.exit_code == 1
    monkeypatch.setattr(cli.httpx, "request", lambda *a, **k: response(500, text="plain"))
    with pytest.raises(typer.Exit):
        cli._api(settings, "GET", "/x")
    monkeypatch.setattr(
        cli.httpx,
        "request",
        lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )
    with pytest.raises(typer.Exit) as unreachable:
        cli._api(settings, "GET", "/x")
    assert unreachable.value.exit_code == 4


def test_user_not_found_branches(tmp_path: Path, monkeypatch) -> None:
    runner = _init(tmp_path, monkeypatch)
    assert runner.invoke(app, ["user", "rotate", "missing"]).exit_code == 1
    assert runner.invoke(app, ["user", "quota", "missing", "--quota", "1G"]).exit_code == 1
    assert runner.invoke(app, ["user", "subscription", "missing"]).exit_code == 1
    assert runner.invoke(app, ["user", "add", "alice", "--json"]).exit_code == 0
    assert '"user": "bob"' in runner.invoke(app, ["user", "add", "bob", "--json"]).output

    import sqlite3

    db = tmp_path / "data" / "ostium.db"
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE proxy_users SET subscription_token_enc=NULL WHERE name='alice'")
        connection.commit()
    assert runner.invoke(app, ["user", "subscription", "alice"]).exit_code == 0


def test_logs_core_missing_and_journalctl(tmp_path: Path, monkeypatch) -> None:
    runner = _init(tmp_path, monkeypatch)
    assert runner.invoke(app, ["logs", "--source", "core"]).exit_code == 4

    calls: list[str] = []

    def fake_exec(name, argv):  # type: ignore[no-untyped-def]
        calls.append(name)
        raise SystemExit(0)

    monkeypatch.setattr(cli.shutil, "which", lambda name: "/bin/journalctl")
    monkeypatch.setattr(cli.os, "execvp", fake_exec)
    assert runner.invoke(app, ["logs"]).exit_code == 0
    assert calls == ["journalctl"]


def test_core_manifest_url_version_and_bad_archive(tmp_path: Path, monkeypatch) -> None:
    runner = _init(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cli.platform, "machine", lambda: "x86_64")

    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        data = b"versioned binary"
        info = tarfile.TarInfo("sing-box")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    content = archive.getvalue()
    import hashlib

    manifest = {
        "artifacts": [
            {
                "os": "linux",
                "arch": "amd64",
                "version": "1.14.4",
                "url": "https://example.com/core.tar.gz",
                "sha256": hashlib.sha256(content).hexdigest(),
            },
            {
                "os": "linux",
                "arch": "amd64",
                "version": "1.13.0",
                "url": "https://example.com/core.tar.gz",
                "sha256": hashlib.sha256(content).hexdigest(),
            },
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    with respx.mock:
        respx.get("https://example.com/manifest.json").mock(
            return_value=httpx.Response(200, json=manifest)
        )
        respx.get("https://example.com/core.tar.gz").mock(
            return_value=httpx.Response(200, content=content)
        )
        result = runner.invoke(
            app,
            [
                "core",
                "install",
                "--manifest",
                "https://example.com/manifest.json",
                "--version",
                "1.13.0",
            ],
        )
    assert result.exit_code == 0, result.output

    empty_archive = io.BytesIO()
    with tarfile.open(fileobj=empty_archive, mode="w:gz") as tar:
        data = b"not the binary"
        info = tarfile.TarInfo("other-file")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    empty_content = empty_archive.getvalue()
    manifest["artifacts"] = [
        {
            "os": "linux",
            "arch": "amd64",
            "version": "1.14.4",
            "url": "https://example.com/empty.tar.gz",
            "sha256": hashlib.sha256(empty_content).hexdigest(),
        }
    ]
    empty_manifest = tmp_path / "empty-manifest.json"
    empty_manifest.write_text(json.dumps(manifest))
    with respx.mock:
        respx.get("https://example.com/empty.tar.gz").mock(
            return_value=httpx.Response(200, content=empty_content)
        )
        bad = runner.invoke(app, ["core", "install", "--manifest", str(empty_manifest)])
    assert bad.exit_code == 6


def test_service_uninstall_success(tmp_path: Path, monkeypatch) -> None:
    runner = _init(tmp_path, monkeypatch)
    monkeypatch.setattr(cli.sys, "platform", "linux")
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)

    unlinked: list[tuple[str, str]] = []
    system_calls: list[str] = []

    class FakePath:
        def __init__(self, *parts: str) -> None:
            self.parts = parts

        def unlink(self, missing_ok: bool = False) -> None:
            unlinked.append(self.parts)

    monkeypatch.setattr(cli, "Path", FakePath)
    monkeypatch.setattr(cli.os, "system", lambda command: system_calls.append(command))
    result = runner.invoke(app, ["service", "uninstall"])
    assert result.exit_code == 0
    assert len(unlinked) == 2
    assert system_calls == ["systemctl daemon-reload"]


def test_cli_module_main_guard(monkeypatch) -> None:
    import runpy

    monkeypatch.setattr("sys.argv", ["ostium", "version"])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("ostium.cli.main", run_name="__main__")
    assert excinfo.value.code == 0


def test_human_bytes_and_parse_bytes() -> None:
    assert cli._human_bytes(0) == "0 B"
    assert cli._human_bytes(1024) == "1.0 KiB"
    assert cli._human_bytes(1024**4) == "1.0 TiB"
    assert cli._human_bytes(1024**5) == "1024.0 TiB"
    assert cli._parse_bytes("1G") == 1024**3
    assert cli._parse_bytes("500m") == 500 * 1024**2
    assert cli._parse_bytes("1024") == 1024
