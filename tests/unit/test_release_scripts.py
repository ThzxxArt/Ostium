from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_coverage_gate_rejects_empty_reports_and_missing_critical_packages(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text('{"files": {}}', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "coverage_gate.py"), str(empty)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "no files" in result.stdout + result.stderr

    partial = tmp_path / "partial.json"
    partial.write_text(
        '{"files": {"src/ostium/api/app.py": {"summary": {'
        '"num_statements": 10, "covered_lines": 10, "num_branches": 2, '
        '"covered_branches": 2}}}}',
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "coverage_gate.py"), str(partial)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "no coverage rows" in result.stdout + result.stderr


def test_release_e2e_scripts_are_executable_and_invoked_with_bash() -> None:
    # A fresh GitHub checkout honours the index mode.  These two scripts were
    # committed as 100644, so the release job failed with "Permission denied"
    # before running any e2e step.  The workflow now also calls them via bash.
    for name in (
        "upgrade-e2e.sh",
        "install-e2e.sh",
        "release-preflight.sh",
        "verify-release.sh",
    ):
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-s", f"scripts/{name}"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.startswith("100755"), result.stdout

    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "bash ./scripts/upgrade-e2e.sh" in workflow
    assert "bash ./scripts/install-e2e.sh" in workflow
    assert "sudo --preserve-env=OSTIUM_INSTALL_E2E_CORE,PATH" in workflow


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
