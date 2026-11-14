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


def test_release_notes_are_not_generated_from_an_empty_template() -> None:
    publish = _release()["jobs"]["publish"]["steps"]
    release = next(step for step in publish if step.get("uses", "").startswith("softprops/"))
    assert release["with"]["body_path"] == "RELEASE_NOTES.md"
    assert (ROOT / "RELEASE_NOTES.md").is_file()


def test_release_macos_uses_an_available_runner_and_names_the_core_arch() -> None:
    assert _release()["jobs"]["macos"]["runs-on"] == "macos-15-intel"
    script = (ROOT / "scripts" / "build-macos.sh").read_text(encoding="utf-8")
    assert "OSTIUM_MACOS_ARCH" in script
    assert '*-darwin-arm64.tar.gz) CORE_ARCH="arm64"' in script
    assert "${CORE_ARCH:-$(uname -m)}" in script


def test_release_docs_describe_the_current_release_as_published() -> None:
    notes = (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    heading = notes.splitlines()[0]
    assert heading.startswith("# Ostium v")
    version = heading.removeprefix("# Ostium v").strip()

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_en = " ".join(
        line.lstrip("> ").lower()
        for line in (ROOT / "README.en.md").read_text(encoding="utf-8").splitlines()
    )
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert f"发布状态：v{version} 已于" in readme
    assert f"当前公开可安装版本为 v{version}" in readme
    assert "尚未发布" not in readme
    assert f"release status: v{version} was published" in readme_en
    assert f"current public release is v{version}" in readme_en
    assert "not yet published" not in readme_en
    assert f"v{version} is the current release" in security
    assert "not published yet" not in security.lower()
    assert f"## [{version}]" in changelog
    assert "pending publication" not in changelog.lower()
    assert "not published yet" not in changelog.lower()
    assert "## publication" in notes.lower()
    assert "published on" in notes.lower()


def test_release_windows_wintun_is_checked_and_located() -> None:
    windows = _release()["jobs"]["windows"]
    prepare = next(
        step for step in windows["steps"] if step.get("name") == "Prepare core and Wintun"
    )
    script = prepare["run"]
    assert "07c256185d6ee3652e09fa55c0b673e2624b565e02c4b9091c79ca7d2f24ef51" in script
    assert "Get-ChildItem dist/wintun -Recurse -Filter wintun.dll" in script
    assert "dist/wintun/bin/amd64/wintun.dll" not in script


def test_linux_package_job_installs_appimage_build_dependencies() -> None:
    job = _release()["jobs"]["linux-packages"]
    runs = "\n".join(str(step.get("run", "")) for step in job["steps"] if isinstance(step, dict))
    assert "desktop-file-utils" in runs
    assert "squashfs-tools" in runs
    assert "install -y file" in runs


def test_linux_package_version_is_normalised_from_the_git_tag() -> None:
    script = (ROOT / "scripts" / "build-linux-packages.sh").read_text(encoding="utf-8")
    assert 'VERSION="${VERSION#v}"' in script
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "build-linux-packages.sh" in workflow
    assert '--version "${{ github.ref_name }}"' in workflow


def test_docker_push_waits_for_platform_artifacts() -> None:
    docker = _release()["jobs"]["docker"]
    assert set(docker["needs"]) >= {
        "verify",
        "wheel",
        "windows",
        "macos",
        "linux-packages",
    }


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
