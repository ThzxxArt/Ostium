from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_windows_release_layout_uses_the_full_service_bundle() -> None:
    build = (ROOT / "scripts" / "build-windows.ps1").read_text(encoding="utf-8")
    assert 'Copy-Item "dist\\OstiumService\\*" "$out\\service"' in build
    assert 'Copy-IfDifferent $CoreBinary "dist\\core\\sing-box.exe"' in build
    assert 'Copy-IfDifferent $WintunDll "dist\\core\\wintun.dll"' in build
    assert "$IsWindows" not in build
    assert 'throw "CoreBinary is required and must exist' in build
    assert 'throw "WintunDll is required and must exist' in build
    assert 'if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }' in build
    assert 'if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed" }' in build
    assert 'throw "Inno Setup (ISCC.exe) is required' in build

    install = (ROOT / "deploy" / "windows" / "install.ps1").read_text(encoding="utf-8")
    assert 'Join-Path $InstallDir "service"' in install
    assert 'Join-Path $ServiceDir "ostium-service.exe"' in install
    assert 'Join-Path $ServiceDir "core.toml"' in install
    assert "[IO.File]::WriteAllText($coreConfig, $coreToml)" in install
    assert "Set-Content -LiteralPath $coreConfig -Encoding utf8" not in install
    assert "$IsWindows" not in install
    assert "WindowsBuiltInRole" in install
    assert "Users:(R" not in install
    assert '"*S-1-5-18:R"' in install
    assert '"${userAccount}:R"' in install
    assert '"Could not secure the core token ACL"' in install
    assert "Could not install the OstiumCore service" in install
    # Task Scheduler cannot reliably start a .cmd as its image; launch the
    # hidden PowerShell wrapper and wait for the UI's health endpoint.
    assert '$uiScript = "$InstallDir\\ostium-ui.ps1"' in install
    assert "New-ScheduledTaskAction -Execute $uiCmd" not in install
    assert "-WindowStyle Hidden" in install
    assert "-WorkingDirectory $InstallDir" in install
    assert "Add-MachinePathEntry -Directory $InstallDir" in install
    assert '$healthUrl = "http://127.0.0.1:8787/healthz"' in install
    assert 'throw "Ostium UI did not become ready' in install
    # A failed privileged core must not prevent the UI from starting.
    assert "$serviceStarted = $false" in install
    assert "OstiumCore service did not start" in install
    assert "Write-InstallLog" in install
    assert "service.log" in install

    uninstall = (ROOT / "deploy" / "windows" / "uninstall.ps1").read_text(encoding="utf-8")
    assert 'Join-Path $InstallDir "service\\ostium-service.exe"' in uninstall
    assert "$proxyRestored" in uninstall
    assert "Could not confirm the system proxy was restored" in uninstall
    assert "Remove-MachinePathEntry -Directory $InstallDir" in uninstall

    setup = (ROOT / "deploy" / "windows" / "ostium.iss").read_text(encoding="utf-8")
    # The client database is in the UI data directory, not the core's
    # ProgramData\OstiumCore tree; snapshotting the wrong tree loses rollback.
    assert "Join-Path $env:ProgramData ''Ostium''" in setup
    assert (
        "Join-Path $env:ProgramData ''OstiumCore''; if(Test-Path (Join-Path $d ''ostium.db'')"
        not in setup
    )
    assert "Get-Process ostium" in setup
    assert 'Filename: "http://127.0.0.1:8787"' in setup
    assert r"SetupIconFile=..\..\assets\brand\ostium.ico" in setup

    service_spec = (ROOT / "deploy" / "pyinstaller" / "ostium-service.spec").read_text(
        encoding="utf-8"
    )
    # uvicorn's loop/protocol classes are imported by name at runtime.
    assert 'collect_submodules("uvicorn")' in service_spec
    assert 'sys.platform == "win32"' in service_spec
    assert "icon=ICON" in service_spec
    ui_spec = (ROOT / "deploy" / "pyinstaller" / "ostium.spec").read_text(encoding="utf-8")
    assert 'sys.platform == "win32"' in ui_spec
    assert "icon=ICON" in ui_spec
    icon = (ROOT / "assets" / "brand" / "ostium.ico").read_bytes()
    assert icon.startswith(b"\x00\x00\x01\x00")

    online = (ROOT / "scripts" / "install-online.ps1").read_text(encoding="utf-8")
    assert "OstiumCore 服务未运行；UI 仍已安装" in online
    assert "ostium-ui.ps1" in online
    assert 'New-ScheduledTaskAction -Execute (Join-Path $installDir "ostium-ui.cmd")' not in online
