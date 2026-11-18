"""Static release packaging and deployment invariant tests."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_distribution_name_is_ostium_ctl() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "ostium-ctl"
    assert project["version"] == (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert (ROOT / project["readme"]).is_file()


def test_docker_build_includes_the_pypi_readme() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "COPY docs/pypi-readme.md ./docs/pypi-readme.md" in dockerfile
    # Docker cannot re-include a file from an excluded directory, so the
    # parent must be excluded with a glob and the file re-included explicitly.
    assert "docs/*" in dockerignore
    assert "!docs/pypi-readme.md" in dockerignore
    assert "\ndocs\n" not in dockerignore


def test_docker_css_build_preserves_tailwind_source_layout() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    # CSS must be built after uv sync, in the same tree that contains both the
    # project templates and Unfold's admin templates.
    assert "uv sync --frozen --no-dev" in dockerfile
    assert "tailwindcss -i src/ostium/static/src/app.css -o src/ostium/static/css/app.css" in dockerfile
    assert "grep -q '\\.table{'" in dockerfile
    css = (ROOT / "src/ostium/static/src/app.css").read_text(encoding="utf-8")
    assert '@source "../../templates/**/*.html"' in css


def test_caddy_does_not_override_subscription_referrer_policy() -> None:
    caddyfile = (ROOT / "deploy/caddy/Caddyfile.example").read_text(encoding="utf-8")
    assert "@console not path /sub/*" in caddyfile
    assert 'header @console Referrer-Policy "same-origin"' in caddyfile
    # A global header would overwrite Django's no-referrer on /sub/*.
    assert '\t\tReferrer-Policy "same-origin"' not in caddyfile


def test_release_workflow_is_manual_and_safe_by_default() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "tags:" not in workflow
    assert "publish_pypi:" in workflow
    assert "default: false" in workflow
    assert "environment: pypi" in workflow
    assert "id-token: write" in workflow
    assert "pypa/gh-action-pypi-publish" in workflow
    assert "scripts/verify-package.py" in workflow
    assert "mkdocs build --strict" in workflow


def test_installer_enforces_option_and_caddy_preconditions() -> None:
    script = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "--with-caddy requires --domain." in script
    assert "Install caddy first" in script
    assert "Install certbot first" in script
    assert '"--pypi and --from-source cannot be used together."' in script
    assert '"--purge is only valid with the uninstall command."' in script
    assert "ostium-ctl==${PYPI_VERSION}" in script
    assert "singbox_version_ok" in script
    assert "constant.Version=v${SINGBOX_VERSION}" in script


def test_container_base_images_are_digest_pinned() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "deploy/docker/compose.yml").read_text(encoding="utf-8")
    for image in ("golang:1.27-bookworm", "debian:bookworm-slim", "python:3.14-slim"):
        assert f"FROM {image}@sha256:" in dockerfile
    assert "ghcr.io/astral-sh/uv:0.11.14@sha256:" in dockerfile
    assert "caddy:2-alpine@sha256:" in compose
    assert "postgres:18-alpine@sha256:" in compose


def test_sdist_includes_installer_and_deployment_assets() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    include = project["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert "install.sh" in include
    assert "deploy" in include
    assert "docs" in include
