from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ostium.cli.main import app

VLESS = (
    "vless://2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e@vpn.example.com:443"
    "?encryption=none&security=reality&sni=www.apple.com&fp=chrome"
    "&pbk=Bs2KLXAKuw5pGFpBIwnyt896Y8mhNJHewMHHY0en6hM&sid=55e1651e#HK"
)


def _init_server(tmp_path: Path, monkeypatch) -> CliRunner:  # type: ignore[no-untyped-def]
    data = tmp_path / "data"
    config = tmp_path / "config"
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


def test_cli_user_lifecycle(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runner = _init_server(tmp_path, monkeypatch)
    assert runner.invoke(app, ["user", "add", "alice", "--quota", "1G"]).exit_code == 0
    assert runner.invoke(app, ["user", "list"]).exit_code == 0
    assert runner.invoke(app, ["user", "show", "alice"]).exit_code == 0
    assert runner.invoke(app, ["user", "disable", "alice"]).exit_code == 0
    assert runner.invoke(app, ["user", "enable", "alice"]).exit_code == 0
    assert runner.invoke(app, ["user", "quota", "alice", "--quota", "2G"]).exit_code == 0
    assert runner.invoke(app, ["user", "subscription", "alice"]).exit_code == 0
    assert runner.invoke(app, ["user", "rotate", "alice"]).exit_code == 0
    output = tmp_path / "alice.json"
    assert runner.invoke(app, ["user", "export", "alice", "--output", str(output)]).exit_code == 0
    assert output.is_file()
    assert runner.invoke(app, ["user", "remove", "alice", "--yes"]).exit_code == 0


def test_cli_profiles_and_backup(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    runner = _init_server(tmp_path, monkeypatch)
    profile_file = tmp_path / "profile.txt"
    profile_file.write_text(VLESS)
    result = runner.invoke(app, ["profile", "import", str(profile_file), "--name", "HK"])
    assert result.exit_code == 0, result.output
    assert runner.invoke(app, ["profile", "list"]).exit_code == 0
    assert runner.invoke(app, ["profile", "remove", "HK", "--yes"]).exit_code == 0

    result = runner.invoke(app, ["backup", "create", "--password", "backup-pass"])
    assert result.exit_code == 0, result.output
    assert runner.invoke(app, ["backup", "list"]).exit_code == 0
    result = runner.invoke(app, ["cert", "list"])
    assert result.exit_code == 0
    result = runner.invoke(
        app, ["diagnostics", "export", "--output", str(tmp_path / "diag.tar.gz")]
    )
    assert result.exit_code == 0
    assert (tmp_path / "diag.tar.gz").is_file()
