# Release status

This page is the single source of truth for what is published, what was
verified, and what remains an accepted blocker. Version-specific notes live in
`CHANGELOG.md` and `RELEASE_NOTES.md`; this page records the delivery facts.

## Current release

| Field | Value |
|---|---|
| Version | **0.1.2** |
| Status | **Preparing; not tagged or published** |
| Previous release | `v0.1.1`, published 2026-11-14 (23 assets, immutable) |
| Release type | State convergence and release integrity; no new protocols |
| Source branch | `release/0.1.2` |

`v0.1.0` and `v0.1.1` tags, GitHub Release assets, PyPI wheels and GHCR images
are published artifacts. They are never replaced or moved by this release.

Known limitation: the `v0.1.1` tag and its PyPI sdist still contain the
pre-publication README wording (“not yet published”) because they were built
before the status update. Replacing them would rewrite published artifacts;
0.1.2 fixes the status at its own tag instead.

## 0.1.2 verification status

### Verified locally

- Backend unit and in-process integration tests: 651 passed / 10 deselected;
  94.07% statements / 90.38% branches; `coverage_gate.py` passes.
- Real sing-box integration tests with the pinned `1.14.4-ostium.1` core: 10 passed.
- Frontend typecheck, lint, unit tests, production build and formatting: 192
  passed; 90.69/85.13/88.08/92.17.
- `0.1.1 -> 0.1.2` upgrade script: user, password material, subscription
  token, database, backup and `master.key` survive; a 0.1.1 backup restores.
- Cross-directory backup restore (v2 streaming), missing-master-key rejection,
  checksum/tamper/truncation rejection and v1 backup import.
- Rule/RE2 validation, rule-set format validation, rule-set-only tester
  semantics and DNS pinning tests.
- First full review round: 40 findings closed, including commit-before-response,
  stats-outage quota enforcement, certificate path traversal, webhook secret
  encryption, Public UI recovery and release-workflow/Docker defaults. See
  `V0.1.2_REVIEW_ROUND1.md`.
- Release workflow ordering tests: draft release first, PyPI before GHCR/draft
  publication.
- Playwright/axe/visual regression: 69 passed after the review changes
  (1440/1024/390, dark/light, core-page axe, LCP/CLS and PWA checks).

### Not verified in this workspace

These items require external hardware, accounts, runners or time. They are
**not** claimed as verified:

- Windows 11 runtime: setup, service, TUN/Wintun, PAC, SmartScreen, uninstall.
- macOS 14 runtime: launchd, utun, system proxy, DMG, Gatekeeper, notarization.
- Debian 12/13, RHEL 9, non-systemd (OpenRC/runit/s6/supervisor) real machines.
- Nginx TLS/WebSocket/IP allowlist on a real reverse proxy.
- Docker amd64/arm64 runtime, volume upgrade and digest promotion.
- ACME staging/production issuance and renewal against a real domain.
- Real TUN, Allow LAN, DNS leak, 72-hour soak, iperf3 performance and
  5-user usability measurements.
- Windows Authenticode and Apple Developer ID signing certificates.
- Separation of the control-plane and core service users (currently both use
  `ostium`; tracked as a 0.2.0 architecture item).

### Signing status

No Windows Authenticode or Apple Developer ID certificate is configured in this
repository. Until the release owner supplies one, affected assets must be
listed as **unsigned** in the release notes. Checksums and GitHub build
provenance are not a substitute for platform code signing.

The release workflow expects a protected GitHub environment named
`release-signing` with required reviewers for the Windows/macOS jobs. Create it
before tagging; otherwise those jobs will not start.

## Release gates for 0.1.2

1. **Code and automation**: ruff, mypy, shellcheck, mkdocs strict, backend and
   frontend suites, real-core integration, coverage gates.
2. **Upgrade and data**: `0.1.1 -> 0.1.2` upgrade and rollback; backup restore;
   missing-key and corruption rejection.
3. **Platform evidence**: record only what was actually executed; unexecuted
   items stay blockers.
4. **Publication ordering**: draft release verified first, PyPI published only
   after that verification, then GHCR version/latest tags promoted and the draft
   made public. PyPI is the first irreversible public step; a later failure keeps
   the draft for retry and requires a yank/patch if it cannot be completed.

## Rollback

- **Before publication**: delete the draft release and local tag; published
  versions are untouched.
- **After PyPI succeeds but the draft cannot be published**: keep the draft,
  fix the publication step, or yank the PyPI version and publish a patch.
- **Installation failure**: restore the previous virtualenv and the database
  snapshot; the installer keeps its staged/venv rollback files for diagnosis.
- **Restore failure**: the staged backup is kept for retry and the previous
  database is restored before an error is returned.
