#!/usr/bin/env python3
"""Verify the built wheel/sdist before they are published.

This script intentionally uses only the standard library so the release job can
run it without installing the project first.
"""

from __future__ import annotations

import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

PROJECT_NAME = "ostium-ctl"
REQUIRED_WHEEL_FILES = (
    "ostium/accounts/migrations/0001_initial.py",
    "ostium/templates/console/base.html",
    "ostium/static/css/app.css",
    "ostium/static/js/htmx.min.js",
    "ostium/static/fonts/inter-latin-wght-normal.woff2",
)
REQUIRED_SDIST_FILES = (
    "pyproject.toml",
    "docs/pypi-readme.md",
    "deploy/systemd/ostium-web.service",
    "install.sh",
)


def _fail(message: str) -> None:
    raise SystemExit(f"verify-package: {message}")


def _metadata(archive: zipfile.ZipFile) -> dict[str, str]:
    names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
    if len(names) != 1:
        _fail(f"expected exactly one METADATA file, found {len(names)}")
    values: dict[str, str] = {}
    for line in archive.read(names[0]).decode("utf-8").splitlines():
        if not line:
            break
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    return values


def main(argv: list[str]) -> int:
    dist = Path(argv[1] if len(argv) > 1 else "dist")
    expected_version = Path("VERSION").read_text(encoding="utf-8").strip()
    with Path("pyproject.toml").open("rb") as handle:
        project_version = tomllib.load(handle)["project"]["version"]
    if expected_version != project_version:
        _fail(f"VERSION ({expected_version}) does not match pyproject.toml ({project_version})")

    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1:
        _fail(f"expected exactly one wheel in {dist}, found {len(wheels)}")
    if len(sdists) != 1:
        _fail(f"expected exactly one sdist in {dist}, found {len(sdists)}")

    wheel = wheels[0]
    if not wheel.name.startswith("ostium_ctl-"):
        _fail(f"unexpected wheel filename: {wheel.name}")
    with zipfile.ZipFile(wheel) as archive:
        metadata = _metadata(archive)
        if metadata.get("Name") != PROJECT_NAME:
            _fail(f"wheel name is {metadata.get('Name')!r}, expected {PROJECT_NAME!r}")
        if metadata.get("Version") != expected_version:
            _fail(f"wheel version is {metadata.get('Version')!r}, expected {expected_version!r}")
        missing = [name for name in REQUIRED_WHEEL_FILES if name not in archive.namelist()]
    if missing:
        _fail(f"wheel is missing required files: {', '.join(missing)}")

    sdist = sdists[0]
    with tarfile.open(sdist) as archive:
        names = archive.getnames()
    missing = [
        required
        for required in REQUIRED_SDIST_FILES
        if not any(name == required or name.endswith(f"/{required}") for name in names)
    ]
    if missing:
        _fail(f"sdist is missing required files: {', '.join(missing)}")

    print(f"verified {wheel.name} ({PROJECT_NAME} {expected_version}) and {sdist.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
