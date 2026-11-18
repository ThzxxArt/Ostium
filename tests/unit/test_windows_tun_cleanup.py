from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from ostium.system import windows_tun


def test_cleanup_script_only_targets_ostium_adapters_and_routes() -> None:
    script = windows_tun.cleanup_script("ostium0")
    assert "Get-NetAdapter -IncludeHidden" in script
    assert "ostium0" in script
    assert "Remove-NetRoute" in script
    assert "Disable-NetAdapter" in script
    assert "Ostium|sing-box" in script


def test_cleanup_script_escapes_the_interface_name() -> None:
    script = windows_tun.cleanup_script("ostium'0")
    assert "ostium''0" in script
    assert "ostium'0'" not in script


def test_cleanup_is_a_no_op_off_windows() -> None:
    assert windows_tun.cleanup_stale_tun() == {"ok": True, "skipped": "not windows"}


def test_cleanup_reports_powershell_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(windows_tun.os, "name", "nt")
    monkeypatch.setattr(
        windows_tun.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "access denied"),
    )
    result = windows_tun.cleanup_stale_tun("ostium0")
    assert result["ok"] is False
    assert result["returncode"] == 1
    assert "access denied" in str(result["error"])


def test_cleanup_returns_the_removed_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def run(command, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(command)
        assert kwargs["timeout"] == 7
        return SimpleNamespace(returncode=0, stdout="adapters=1 routes=2\n", stderr="")

    monkeypatch.setattr(windows_tun.os, "name", "nt")
    monkeypatch.setattr(windows_tun.subprocess, "run", run)
    result = windows_tun.cleanup_stale_tun("ostium0", timeout=7)
    assert result["ok"] is True
    assert result["output"] == "adapters=1 routes=2"
    assert calls and calls[0][0] == "powershell.exe"
