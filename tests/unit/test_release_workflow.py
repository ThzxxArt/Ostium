from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _release() -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())


def test_release_gates_publication_on_verification() -> None:
    jobs = _release()["jobs"]
    assert "verify" in jobs
    assert set(jobs["publish"]["needs"]) == {
        "verify",
        "wheel",
        "core",
        "windows",
        "macos",
        "linux-packages",
        "docker",
    }
    assert jobs["publish"]["environment"] == "pypi"
    verify_runs = "\n".join(
        str(step.get("run", "")) for step in jobs["verify"]["steps"] if isinstance(step, dict)
    )
    assert "coverage_gate.py" in verify_runs
    assert "pip-audit" in verify_runs
    assert "npm run test:coverage" in verify_runs
    assert "mkdocs build --strict" in verify_runs
    assert "shellcheck" in verify_runs
    assert "npx playwright test" in verify_runs


def test_release_publishes_every_checksummed_asset() -> None:
    workflows = _release()["jobs"]
    publish_steps = workflows["publish"]["steps"]
    checksums = next(step for step in publish_steps if step.get("name") == "Checksums")["run"]
    assert "sha256sum -c SHA256SUMS" in checksums
    stage = next(step for step in publish_steps if step.get("name") == "Stage flat release assets")[
        "run"
    ]
    assert "scripts/install-online.sh" in stage
    assert "scripts/install-online.ps1" in stage
    assert "dist/release" in stage
    release = next(step for step in publish_steps if step.get("uses", "").startswith("softprops/"))
    files = release["with"]["files"]
    for asset in (
        "dist/release/*.whl",
        "dist/release/*.tar.gz",
        "dist/release/install-online.sh",
        "dist/release/install-online.ps1",
        "dist/release/*.sha256",
        "dist/release/*-setup.exe",
        "dist/release/SHA256SUMS",
    ):
        assert asset in files


def test_release_windows_wintun_is_checked_and_located() -> None:
    windows = _release()["jobs"]["windows"]
    prepare = next(
        step for step in windows["steps"] if step.get("name") == "Prepare core and Wintun"
    )
    script = prepare["run"]
    assert "07c256185d6ee3652e09fa55c0b673e2624b565e02c4b9091c79ca7d2f24ef51" in script
    assert "Get-ChildItem dist/wintun -Recurse -Filter wintun.dll" in script
    assert "dist/wintun/bin/amd64/wintun.dll" not in script


def test_release_publishes_both_docker_version_tags() -> None:
    docker = _release()["jobs"]["docker"]
    metadata = next(
        step
        for step in docker["steps"]
        if step.get("uses", "").startswith("docker/metadata-action")
    )
    tags = metadata["with"]["tags"]
    assert "type=semver,pattern={{version}}" in tags
    assert "type=semver,pattern=v{{version}}" in tags
    assert "latest" in tags
