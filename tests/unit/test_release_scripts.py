from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_core_manifest_points_at_the_ostium_release_tag(tmp_path: Path) -> None:
    core = tmp_path / "ostium-core-1.14.4-ostium.1-linux-amd64.tar.gz"
    core.write_bytes(b"core archive")
    output = tmp_path / "manifest.json"

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build-core-manifest.py"),
            "--dir",
            str(tmp_path),
            "--release-version",
            "v0.2.0",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    manifest = json.loads(output.read_text())
    assert manifest["format"] == "ostium-core-manifest"
    assert len(manifest["artifacts"]) == 1
    artifact = manifest["artifacts"][0]
    assert artifact["version"] == "1.14.4-ostium.1"
    assert artifact["url"].endswith("/v0.2.0/ostium-core-1.14.4-ostium.1-linux-amd64.tar.gz")
    assert "v1.14.4/" not in artifact["url"]
