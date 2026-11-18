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
    assert "tailwindcss -i src/ostium/static_src/app.css -o src/ostium/static/css/app.css" in dockerfile
    assert "grep -q '\\.table{'" in dockerfile
    css = (ROOT / "src/ostium/static_src/app.css").read_text(encoding="utf-8")
    assert '@source "../templates/**/*.html"' in css


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


def test_installer_uses_release_assets_by_default() -> None:
    script = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "prepare_release_assets" in script
    assert "ostium_ctl-${RELEASE_VERSION}-py3-none-any.whl" in script
    assert "ostium_ctl-${RELEASE_VERSION}.tar.gz" in script
    assert "sha256sum -c --ignore-missing SHA256SUMS" in script
    assert '"$RELEASE_WHEEL"' in script
    assert '"$RELEASE_SINGBOX"' in script
    assert "--version VERSION" in script
    assert 'if [ "$FROM_SOURCE" -eq 1 ]; then\n    prepare_source\n  else\n    prepare_release_assets' in script


def test_static_source_and_chart_bundle_are_production_safe() -> None:
    assert (ROOT / "src/ostium/static_src/app.css").is_file()
    assert not (ROOT / "src/ostium/static/src/app.css").exists()
    chart = (ROOT / "src/ostium/static/js/chart.umd.min.js").read_text(encoding="utf-8")
    assert "sourceMappingURL" not in chart


def test_installer_forces_a_managed_python_readable_by_the_service_user() -> None:
    script = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "UV_PYTHON_PREFERENCE" in script
    assert "only-managed" in script
    assert "UV_PYTHON_BIN_DIR" in script
    assert 'readlink -f "$PREFIX/venv/bin/python"' in script
    assert "The venv Python resolves outside" in script
    assert 'chmod -R a+rX "$PREFIX/venv"' in script


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
