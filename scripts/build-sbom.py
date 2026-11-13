#!/usr/bin/env python3
"""Generate a CycloneDX 1.5 SBOM for the installed Ostium wheel.

Only standard-library modules are used so the release workflow can run this
without extra build dependencies.  Core SBOMs are produced separately by
``scripts/build-core.sh`` (``SBOM.txt`` from ``go version -m``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from importlib.metadata import PackageNotFoundError, distribution, version
from pathlib import Path


def _component(name: str, package_version: str, *, kind: str = "library") -> dict[str, object]:
    return {
        "type": kind,
        "name": name,
        "version": package_version,
        "purl": f"pkg:pypi/{name}@{package_version}",
    }


def build_sbom() -> dict[str, object]:
    try:
        app_version = version("ostium-ctl")
        metadata = distribution("ostium-ctl")
        requires = metadata.requires or []
    except PackageNotFoundError:
        app_version = "0.1.1"
        requires = []
    components: list[dict[str, object]] = []
    seen: set[str] = set()
    for requirement in requires:
        name = requirement.split(";", 1)[0].strip()
        for separator in ("[", "(", "=", "<", ">", "!", "~", " "):
            name = name.split(separator, 1)[0]
        name = name.strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        try:
            components.append(_component(name, version(name)))
        except PackageNotFoundError:
            components.append({"type": "library", "name": name})
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "ostium-ctl",
                "version": app_version,
                "licenses": [{"license": {"id": "GPL-3.0-or-later"}}],
            }
        },
        "components": components,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("dist/ostium-sbom.cdx.json"))
    args = parser.parse_args()
    payload = build_sbom()
    body = json.dumps(payload, indent=2, ensure_ascii=False).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    print(f"wrote {args.output} sha256={digest}")


if __name__ == "__main__":
    main()
