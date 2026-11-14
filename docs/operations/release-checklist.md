# Release checklist (v0.1.x)

This checklist is executed by the release owner. It is intentionally immutable:
a published asset is never replaced.

## Before tagging

- [ ] All P0/P1/P2 work items closed or explicitly blocked with owner.
- [ ] PR/main CI green for Python and frontend gates; release `verify` workflow
      additionally green for shellcheck, PowerShell parse, mkdocs `--strict`,
      Playwright/axe/visual, pip-audit and npm audit.
- [ ] Version audit: `pyproject.toml`, `src/ostium/__init__.py`, installers,
      Inno, Docker/compose, manifest, README/docs.
- [ ] DEB/AppImage filenames and Debian `Version:` use `X.Y.Z`, never `vX.Y.Z`
      (the build script strips the tag prefix).
- [ ] README.md, README.en.md, SECURITY.md, CHANGELOG.md and RELEASE_NOTES.md
      describe `vX.Y.Z` as the release being published; no "not yet published"
      or "pending publication" text remains, and the release-docs test passes.
      Update this status before tagging so the tagged tree never advertises the
      release as unpublished after assets go live. If publication fails before
      any asset exists, revert the status text before retrying.
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
- [ ] PyPI `ostium-ctl==X.Y.Z` and GHCR tags `X.Y.Z`/`vX.Y.Z`/`latest`
      published.

## Read-only verification

- [ ] `scripts/verify-release.sh --version X.Y.Z` downloads every asset and
      `sha256sum -c SHA256SUMS` passes.
- [ ] `gh attestation verify` for every asset.
- [ ] Online installer, PyPI install and GHCR pull tested.
- [ ] `/healthz`, `/readyz`, login, subscription and core status checked.
- [ ] README/README.en/SECURITY/CHANGELOG and the GitHub Release body show the
      published version with no stale status text. Correct docs on `main` if not.
- [ ] No asset changed after publication. Any fix goes to the next patch.
