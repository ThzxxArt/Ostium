# Release status

This page is the single source of truth for what is published, what was
verified, and what remains an accepted blocker. Version-specific notes live in
`CHANGELOG.md` and `RELEASE_NOTES.md`; this page records the delivery facts.

## Current release

| Field | Value |
|---|---|
| Version | **0.1.2** |
| Status | **Published** |
| Tag | `v0.1.2` (annotated, commit `7f9ea6a`) |
| Assets | GitHub Release `v0.1.2` — 23 assets, marked Latest |
| PyPI | `ostium-ctl==0.1.2` (wheel + sdist) |
| GHCR | `0.1.2`, `v0.1.2`, `latest` — linux/amd64 + linux/arm64 |
| Release workflow | run `43682022358` — success |
| Previous release | `v0.1.1`, published 2026-11-14 (23 assets, unchanged) |
| Release type | State convergence and release integrity; no new protocols |
| Source branch | `main` (`release/0.1.2` merged at `683ebf3`) |

`v0.1.0` and `v0.1.1` tags, GitHub Release assets, PyPI wheels and GHCR images
are published artifacts. They are never replaced or moved by this release.

Known limitation: the `v0.1.1` tag and its PyPI sdist still contain the
pre-publication README wording (“not yet published”) because they were built
before the status update. Replacing them would rewrite published artifacts;
0.1.2 fixes the status at its own tag instead.

## 0.1.2 verification status

### Verified locally

- Backend unit and in-process integration tests: 707 passed / 10 deselected;
  94.29% statements / 90.44% branches; `coverage_gate.py` passes.
- Real sing-box integration tests with the pinned `1.14.4-ostium.1` core: 10 passed.
- Frontend typecheck, lint, unit tests, production build and formatting: 203
  passed; 90.82/85.91/88.54/92.37.
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
- Second full review round: 19 additional findings closed, including an
  apply-failure path that un-approved a committed inbound port, blocking DNS
  resolution on the event loop, a non-Public-UI certificate renewal switching
  the plaintext control plane to HTTPS, Public UI cookies without `Secure`,
  one-time credentials lost on a post-commit apply error, and release-checklist
  wording that still claimed no post-PyPI half-publication. See
  `V0.1.2_REVIEW_ROUND2.md`.
- Release workflow ordering tests: draft release first, PyPI before GHCR/draft
  publication.
- Playwright/axe/visual regression: 69 passed against the built SPA and the
  current backend with one worker (1440/1024/390, dark/light, core-page axe,
  LCP/CLS and PWA checks). The visual snapshots are deterministic: the clock is
  frozen and every API path they render is mocked.
- Final pre-release review round: 13 P1 findings and one P2 fixed with tests
  that fail on `683ebf3` (core artifact body limit, split-user client watchdog,
  CLI disable/delete tombstones, export certificate resolution, certificate
  replacement recovery, subscription-refresh error persistence, installer
  reinstall and upgrade snapshots on Linux/macOS/Windows, validation-error
  serialization, coverage-gate stability). See `V0.1.2_REVIEW_ROUND4.md`.
- Publication verification: `scripts/verify-release.sh --version 0.1.2`
  downloaded all 23 assets, `sha256sum -c SHA256SUMS` passed, all five core
  platforms are present, build attestations verified, and PyPI reports
  `ostium-ctl==0.1.2`. The wheel and sdist SHA-256 values match between the
  GitHub Release and PyPI.

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
`release-signing` with required reviewers for the Windows/macOS jobs. Create and
configure it (required reviewers, deployment branches) before tagging. GitHub
creates a missing referenced environment automatically **without** protection
rules, so the jobs would start unsigned rather than being blocked. The `pypi`
environment must be protected the same way; a `v*` tag push must not be able to
publish without release-owner approval (D-115).

## Release decisions for 0.1.2

The release owner accepted the following in `V0.1.2_DECISIONS.md`; the RC
evidence is in `V0.1.2_RC_REPORT.md`:

- **D-111** PyPI-first ordering is accepted with the documented retry/yank/patch
  recovery; publication is not atomic.
- **D-112** Control-plane/core service isolation remains a 0.2.0 item.
- **D-113** The unit-only 75/65 coverage target is deferred; the repository and
  package gate at 94.29/90.44 is the release gate.
- **D-114** Linux is Tier 1; Windows/macOS are Tier 2 and published unsigned
  unless signing credentials are supplied.
- **D-115** Push, tag and publication require explicit release-owner approval.

## Release gates for 0.1.2

1. **Code and automation**: ruff, mypy, shellcheck, mkdocs strict, backend and
   frontend suites, real-core integration, coverage gates.
2. **Upgrade and data**: `0.1.1 -> 0.1.2` upgrade plus backup restore;
   missing-key and corruption rejection. The installer's staged rollback files
   and the database snapshot are the recovery path if health checks fail.
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
