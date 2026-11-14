"""The release version must come from VERSION everywhere (P0-06)."""

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
        "src/ostium/__init__.py": f'__version__ = "{VERSION}"',
        "web/package.json": f'"version": "{VERSION}"',
        "web/package-lock.json": f'"version": "{VERSION}"',
        "Dockerfile": f"ARG OSTIUM_VERSION={VERSION}",
        "deploy/docker/docker-compose.yml": f"ostium:{VERSION}",
        "scripts/build-windows.ps1": f'[string]$Version = "{VERSION}"',
        "scripts/build-sbom.py": f'app_version = "{VERSION}"',
    }
    for relative, needle in checks.items():
        assert needle in (ROOT / relative).read_text(encoding="utf-8"), relative


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
        "web/package.json",
        "pyproject.toml",
        "src/ostium/__init__.py",
    ]
    for relative in files:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert not re.search(r"(?<![0-9])0\.1\.[01](?![0-9])", text), relative
