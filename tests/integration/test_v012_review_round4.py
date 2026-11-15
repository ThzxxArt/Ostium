"""Regression tests for the final v0.1.2 pre-release review round."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from ostium.cli import main as cli_main
from ostium.config import Settings


def _init_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[CliRunner, Path]:
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
            "--data-dir",
            str(data),
            "--config-dir",
            str(config),
            "--password",
            "verysecret123",
            "--dev",
        ],
    )
    assert result.exit_code == 0, result.output
    return runner, data


def _enforcement_names(data: Path) -> set[str]:
    path = data / "enforcement.json"
    if not path.is_file():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8"))["users"])


def test_cli_disable_and_delete_write_core_tombstones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner, data = _init_server(tmp_path, monkeypatch)
    created = runner.invoke(
        cli_main.app, ["--allow-degraded", "user", "add", "alice", "--quota", "1G"]
    )
    assert created.exit_code == 0, created.output

    disabled = runner.invoke(cli_main.app, ["--allow-degraded", "user", "disable", "alice"])
    assert disabled.exit_code == 0, disabled.output
    assert "alice" in _enforcement_names(data)

    enabled = runner.invoke(cli_main.app, ["--allow-degraded", "user", "enable", "alice"])
    assert enabled.exit_code == 0, enabled.output
    assert "alice" not in _enforcement_names(data)

    removed = runner.invoke(cli_main.app, ["--allow-degraded", "user", "remove", "alice", "--yes"])
    assert removed.exit_code == 0, removed.output
    # The row is gone, so only the tombstone can stop an old last-good file
    # from resurrecting the credential after a core restart.
    assert "alice" in _enforcement_names(data)


def test_user_export_resolves_relative_certificate_paths(
    api_client: TestClient, session_token: str, settings: Settings
) -> None:
    """API export must see the same TLS endpoints as a subscription.

    New certificate rows are stored relative to the data directory.  Calling
    ``endpoints_for_user`` without the Settings object resolved those paths
    against the process working directory, silently dropping Hysteria2 and
    Trojan from exports and bulk exports.
    """

    issued = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "vpn.example.com", "method": "self-signed"},
        headers={"X-CSRF-Token": session_token},
    )
    assert issued.status_code == 202, issued.text
    certificate = issued.json()["certificate"]
    assert certificate["domain"] == "vpn.example.com"
    with sqlite3.connect(settings.paths.db_path) as connection:
        stored_cert_path = connection.execute(
            "SELECT cert_path FROM certificates WHERE domain = 'vpn.example.com'"
        ).fetchone()[0]
    assert not Path(stored_cert_path).is_absolute()

    enabled = api_client.patch(
        "/api/v1/inbounds/hysteria2",
        json={"enabled": True},
        headers={"X-CSRF-Token": session_token},
    )
    assert enabled.status_code == 200, enabled.text
    # Trojan and VLESS share TCP/443, so enabling Trojan deliberately disables
    # VLESS.  Both TLS inbounds must still appear in the export.
    trojan = api_client.patch(
        "/api/v1/inbounds/trojan",
        json={"enabled": True},
        headers={"X-CSRF-Token": session_token},
    )
    assert trojan.status_code == 200, trojan.text

    created = api_client.post(
        "/api/v1/users",
        json={"name": "alice", "quota_bytes": 0, "quota_cycle": "total"},
        headers={"X-CSRF-Token": session_token},
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["user"]["id"]

    exported = api_client.get(f"/api/v1/users/{user_id}/export")
    assert exported.status_code == 200, exported.text
    protocols = {endpoint["protocol"] for endpoint in exported.json()["endpoints"]}
    assert {"hysteria2", "trojan"} <= protocols
    assert all(endpoint["server"] for endpoint in exported.json()["endpoints"])
