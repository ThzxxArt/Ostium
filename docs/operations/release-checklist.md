# Release checklist (v0.1.x)

This checklist is executed by the release owner. It is intentionally immutable:
a published asset is never replaced.

## Before tagging

- [ ] All P0/P1/P2 work items closed or explicitly blocked with owner.
- [ ] `main` green: ruff, format, mypy, backend coverage gate, frontend coverage,
      Playwright/axe/visual, shellcheck, PowerShell parse, mkdocs `--strict`,
      pip-audit, npm audit.
- [ ] Version audit: `pyproject.toml`, `src/ostium/__init__.py`, installers,
      Inno, Docker/compose, manifest, README/docs.
- [ ] `CHANGELOG.md`, migration guide and release notes drafted.
- [ ] Clean install on Linux, Windows and macOS evidence archived.
- [ ] Nginx/Docker/ACME/TUN/soak/performance/5-user evidence archived.
- [ ] Signing status confirmed; unsigned assets labelled unsigned.
- [ ] `SHA256SUMS` and SBOM generated from the same commit.

## Tag and publish

- [ ] Create exactly one annotated `vX.Y.Z` tag on the final commit; push once.
- [ ] Release workflow builds wheel/sdist, five core archives, Windows setup,
      macOS DMG, Linux DEB/AppImage, Docker, installers, manifest, SBOM and
      `SHA256SUMS` from that tag.
- [ ] Confirm `overwrite_files: false`; never re-run publication to replace an
      existing asset.
- [ ] PyPI `ostium-ctl==X.Y.Z` and GHCR tags published.

## Read-only verification

- [ ] `scripts/verify-release.sh --version X.Y.Z` downloads every asset and
      `sha256sum -c SHA256SUMS` passes.
- [ ] `gh attestation verify` for every asset.
- [ ] Online installer, PyPI install and GHCR pull tested.
- [ ] `/healthz`, `/readyz`, login, subscription and core status checked.
- [ ] No asset changed after publication. Any fix goes to the next patch.
