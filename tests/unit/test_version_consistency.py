"""The release version must come from VERSION everywhere (P0-01)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_version_file_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+([.-][0-9A-Za-z.-]+)?", VERSION)


def test_live_version_sources_match_version_file() -> None:
    checks = {
        "pyproject.toml": f'fallback_version = "{VERSION}"',
        "web/package.json": f'"version": "{VERSION}"',
        "web/package-lock.json": f'"version": "{VERSION}"',
        "Dockerfile": f"ARG OSTIUM_VERSION={VERSION}",
        "deploy/docker/docker-compose.yml": "ostium:latest",
        "deploy/windows/ostium.iss": f'#define AppVersion "{VERSION}"',
        "scripts/build-windows.ps1": f'[string]$Version = "{VERSION}"',
        "scripts/build-linux-packages.sh": f"|| echo {VERSION}",
        "scripts/build-macos.sh": f"|| echo {VERSION}",
        "scripts/build-sbom.py": f'app_version = "{VERSION}"',
    }
    for relative, needle in checks.items():
        assert needle in (ROOT / relative).read_text(encoding="utf-8"), relative


def test_runtime_version_is_not_a_hardcoded_literal() -> None:
    init = (ROOT / "src/ostium/__init__.py").read_text(encoding="utf-8")
    assert "from ostium.build_info import build_info" in init
    assert "__version__ = _BUILD.version" in init
    assert re.search(r'__version__\s*=\s*"\d', init) is None


def test_installers_follow_latest_instead_of_a_pinned_release() -> None:
    shell = (ROOT / "scripts/install-online.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "scripts/install-online.ps1").read_text(encoding="utf-8")
    assert 'VERSION="${OSTIUM_VERSION:-latest}"' in shell
    assert '[string]$Version = "latest"' in powershell


def test_no_live_file_pins_an_older_release() -> None:
    files = [
        "scripts/install-online.sh",
        "scripts/install-online.ps1",
        "scripts/build-linux-packages.sh",
        "scripts/build-macos.sh",
        "scripts/build-windows.ps1",
        "scripts/build-sbom.py",
        "scripts/build-core-manifest.py",
        "Dockerfile",
        "deploy/docker/docker-compose.yml",
        "deploy/windows/ostium.iss",
        "web/package.json",
        "pyproject.toml",
    ]
    current = tuple(int(part) for part in VERSION.split(".")[:3])
    old_versions = [f"0.1.{patch}" for patch in range(current[2]) if (0, 1, patch) != current]
    pattern = re.compile(
        r"(?<![0-9])(" + "|".join(re.escape(item) for item in old_versions) + r")(?![0-9])"
    )
    for relative in files:
        text = (ROOT / relative).read_text(encoding="utf-8")
        match = pattern.search(text)
        assert match is None, f"{relative} pins {match.group(1) if match else ''}"
