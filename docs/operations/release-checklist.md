# Release checklist (v0.1.x)

This checklist is executed by the release owner. It is intentionally immutable:
a published asset is never replaced.

## Before tagging

- [ ] All P0/P1/P2 work items closed or explicitly blocked with owner.
- [ ] PR/main CI green for Python and frontend gates; release `verify` workflow
      additionally green for shellcheck, PowerShell parse, mkdocs `--strict`,
      Playwright/axe/visual, pip-audit and npm audit.
- [ ] Version preflight passes: `scripts/release-preflight.sh --tag vX.Y.Z`.
      It checks `VERSION`, Python/web/Docker/installer defaults and README/docs.
- [ ] DEB/AppImage filenames and Debian `Version:` use `X.Y.Z`, never `vX.Y.Z`
      (the build script strips the tag prefix).
- [ ] README.md, README.en.md, SECURITY.md, CHANGELOG.md and RELEASE_NOTES.md
      describe `vX.Y.Z` as the release being published; no "not yet published"
      or "pending publication" text remains, and `release-preflight.sh` reports
      no stale release-status text. Update this status before tagging so the
      tagged tree never advertises the release as unpublished after assets go
      live. If publication fails before any asset exists, revert the status
      text before retrying.
- [ ] `CHANGELOG.md`, migration guide and release notes drafted.
- [ ] Clean install on Linux, Windows and macOS evidence archived.
- [ ] Nginx/Docker/ACME/TUN/soak/performance/5-user evidence archived.
- [ ] Signing status confirmed; unsigned assets labelled unsigned.
- [ ] `SHA256SUMS` and SBOM generated from the same commit.

## Tag and publish

- [ ] Create exactly one annotated `vX.Y.Z` tag on the final commit; push once.
- [ ] Release workflow builds wheel/sdist, five core archives, Windows setup,
      macOS DMG, Linux DEB/AppImage, Docker staging image, installers, manifest,
      SBOM and `SHA256SUMS` from that tag.
- [ ] The workflow creates a **draft** release, verifies its checksum manifest,
      runs real-core integration and `0.1.5 -> current` upgrade e2e, then
      publishes PyPI.
- [ ] Only after PyPI succeeds are GHCR tags `X.Y.Z`/`vX.Y.Z`/`latest`
      promoted from the verified digest, and the draft is made public.
- [ ] A failed run before PyPI leaves a draft and staging image only. PyPI is
      the first irreversible public step: a later GHCR/draft failure keeps the
      draft for retry and requires yanking the PyPI version or shipping a patch.

## Read-only verification

- [ ] `scripts/verify-release.sh --version X.Y.Z` downloads every asset and
      `sha256sum -c SHA256SUMS` passes.
- [ ] `gh attestation verify` for every asset.
- [ ] Online installer, PyPI install and GHCR pull tested.
- [ ] `/healthz`, `/readyz`, login, subscription and core status checked.
- [ ] README/README.en/SECURITY/CHANGELOG and the GitHub Release body show the
      published version with no stale status text. Correct docs on `main` if not.
- [ ] No asset changed after publication. Any fix goes to the next patch.
