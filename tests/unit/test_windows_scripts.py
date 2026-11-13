from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_windows_release_layout_uses_the_full_service_bundle() -> None:
    build = (ROOT / "scripts" / "build-windows.ps1").read_text(encoding="utf-8")
    assert 'Copy-Item "dist\\OstiumService\\*" "$out\\service"' in build
    assert 'Copy-IfDifferent $CoreBinary "dist\\core\\sing-box.exe"' in build
    assert 'Copy-IfDifferent $WintunDll "dist\\core\\wintun.dll"' in build

    install = (ROOT / "deploy" / "windows" / "install.ps1").read_text(encoding="utf-8")
    assert 'Join-Path $InstallDir "service"' in install
    assert 'Join-Path $ServiceDir "ostium-service.exe"' in install
    assert 'Join-Path $ServiceDir "core.toml"' in install

    uninstall = (ROOT / "deploy" / "windows" / "uninstall.ps1").read_text(encoding="utf-8")
    assert 'Join-Path $InstallDir "service\\ostium-service.exe"' in uninstall
