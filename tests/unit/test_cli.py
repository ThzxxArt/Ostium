from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ostium.cli.main import app


def test_cli_version() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "Ostium" in result.output


def test_cli_client_init_and_user_list(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    data = tmp_path / "data"
    config = tmp_path / "config"
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(data))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(config))
    monkeypatch.setenv("OSTIUM_ROLE", "client")
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "init",
            "--role",
            "client",
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
    result = runner.invoke(app, ["user", "list", "--json"])
    assert result.exit_code == 0
    assert "[]" in result.output
    result = runner.invoke(app, ["backup", "list"])
    assert result.exit_code == 0
