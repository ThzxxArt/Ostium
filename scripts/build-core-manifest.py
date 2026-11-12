#!/usr/bin/env python3
"""Create the signed core manifest consumed by the installer and updater."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

NAME_RE = re.compile(
    r"^ostium-core-(?P<version>.+)-(?P<os>linux|darwin|windows)-"
    r"(?P<arch>amd64|arm64)\.tar\.gz$"
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=Path("dist/core"))
    parser.add_argument(
        "--base-url", default="https://github.com/ThzxxArt/Ostium/releases/download"
    )
    parser.add_argument("--output", type=Path, default=Path("dist/core-manifest.json"))
    args = parser.parse_args()

    artifacts = []
    for path in sorted(args.dir.glob("ostium-core-*.tar.gz")):
        match = NAME_RE.match(path.name)
        if not match:
            continue
        version = match.group("version")
        os_name = match.group("os")
        arch = match.group("arch")
        artifacts.append(
            {
                "os": os_name,
                "arch": arch,
                "version": version,
                "filename": path.name,
                "size": path.stat().st_size,
                "sha256": digest(path),
                "url": f"{args.base_url}/v{version.split('-')[0]}/{path.name}",
            }
        )
    manifest = {
        "format": "ostium-core-manifest",
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "artifacts": artifacts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} with {len(artifacts)} artifact(s)")


if __name__ == "__main__":
    main()
