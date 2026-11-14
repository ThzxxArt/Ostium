"""Release ordering must make a partial release impossible (P0-07)."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_release_creates_a_verified_draft_before_pypi() -> None:
    jobs = _workflow()["jobs"]
    steps = jobs["publish"]["steps"]
    names = [step.get("name", "") for step in steps]
    draft = next(
        index
        for index, step in enumerate(steps)
        if step.get("uses", "").startswith("softprops/action-gh-release")
    )
    verify = next(index for index, name in enumerate(names) if name.startswith("Verify the draft"))
    pypi = next(
        index
        for index, step in enumerate(steps)
        if step.get("uses", "").startswith("pypa/gh-action-pypi-publish")
    )
    publish = next(index for index, name in enumerate(names) if name == "Publish the draft release")
    assert draft < verify < pypi < publish
    assert steps[draft]["with"]["draft"] is True


def test_docker_pushes_only_staging_tags_before_promotion() -> None:
    jobs = _workflow()["jobs"]
    docker_steps = jobs["docker"]["steps"]
    metadata = next(step for step in docker_steps if "metadata-action" in step.get("uses", ""))
    tags = metadata["with"]["tags"]
    assert "staging" in tags
    assert "latest" not in tags
    assert "semver" not in tags
    publish_steps = jobs["publish"]["steps"]
    promote = next(
        step for step in publish_steps if step.get("name") == "Promote the verified staging image"
    )
    assert "imagetools create" in promote["run"]
    assert "needs.docker.outputs.digest" in promote["run"]


def test_release_runs_real_core_integration_and_upgrade_e2e() -> None:
    jobs = _workflow()["jobs"]
    assert "integration" in jobs
    assert "upgrade-e2e" in jobs
    assert jobs["publish"]["needs"].count("integration") == 1
    assert jobs["publish"]["needs"].count("upgrade-e2e") == 1
    for job in ("verify", "integration", "upgrade-e2e"):
        steps = jobs[job]["steps"]
        assert any("uv sync --locked" in step.get("run", "") for step in steps), job
    e2e_steps = jobs["upgrade-e2e"]["steps"]
    assert any("upgrade-e2e.sh" in step.get("run", "") for step in e2e_steps)
    assert any("install-e2e.sh" in step.get("run", "") for step in e2e_steps)
