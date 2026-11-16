# Release status

This page is the single source of truth for what is published, what was
verified, and what remains an accepted blocker. Version-specific notes live in
`CHANGELOG.md` and `RELEASE_NOTES.md`; this page records the delivery facts.

## Current release

| Field | Value |
|---|---|
| Version | **0.1.9** |
| Status | **Published** |
| Tag | `v0.1.9` (annotated, commit `fa35e2e`) |
| Assets | GitHub Release `v0.1.9` — 23 assets, marked Latest |
| PyPI | `ostium-ctl==0.1.9` (wheel + sdist) |
| GHCR | `0.1.9`, `v0.1.9`, `latest` — linux/amd64 + linux/arm64 |
| Release workflow | run `43842024068` — success |
| Previous release | `v0.1.8`, published 2026-11-16 (23 assets, unchanged) |
| Release type | Server IPv4-only DNS/egress patch; no client reinstall required |
| Source branch | `main` |

`v0.1.0` and `v0.1.1` tags, GitHub Release assets, PyPI wheels and GHCR images
are published artifacts. They are never replaced or moved by this release.

Known limitation: the `v0.1.1` tag and its PyPI sdist still contain the
pre-publication README wording (“not yet published”) because they were built
before the status update. Replacing them would rewrite published artifacts;
0.1.9 continues to fix the status at its own tag instead of rewriting published
artifacts.

## 0.1.9 verification status

### Verified locally

- Backend unit and in-process integration tests: 713 passed / 10 deselected;
  94.33% statements / 90.49% branches; `coverage_gate.py` passes.
- Real sing-box integration tests with the pinned `1.14.4-ostium.1` core:
  10 passed.
- Frontend typecheck, lint, unit tests, production build and formatting: 204
  passed; 90.86/85.90/88.63/92.40.
- TOTP regressions: the status endpoint advertises `login_totp_required` before
  login; six password-only attempts leave `failed_attempts=0` and
  `locked_until=NULL`; a wrong TOTP still locks after five failures; a correct
  TOTP logs in after the password-only challenges.
- Windows installer scripts parse with PowerShell 7.7; the generated
  `ostium-ui.ps1` template parses too. The scheduled task uses a hidden
  PowerShell wrapper, waits for `/healthz`, writes `ui.log`, and updates the
  machine PATH.
- 0.1.5 Windows failure reproduced as
  `ModuleNotFoundError: No module named 'aiosqlite'`; both PyInstaller specs now
  collect `aiosqlite`. A local PyInstaller build served `/healthz` after the
  spec fix.
- The 0.1.5 service reproduced SCM error 1053. `sc qc` showed an image path with
  no arguments; the frozen entry point now calls `Initialize`,
  `PrepareToHostSingle` and `StartServiceCtrlDispatcher` itself when SCM starts
  it without arguments. Interactive `debug`/`install`/`remove` still use
  `HandleCommandLine`. Heavy imports run inside `SvcDoRun` after
  `SERVICE_RUNNING`.
- Interactive Windows installs now show a visible PowerShell console with the
  service registration, `Start-Service`, 8787 health check and failure details;
  silent installs stay hidden and write `install.log`.
- The 0.1.7 UI launcher failure was reproduced from `ui.log`: uvicorn started,
  PowerShell emitted `NativeCommandError`, and the wrapper exited with code 1.
  `ostium-ui.ps1` now uses `ErrorActionPreference=Continue`, writes all output
  to `ui.log`, and checks the child exit code.
- Windows installer keeps the UI installable when the service fails, writes
  `install.log`/`service.log`/`service-bootstrap.log`, stops orphan
  `ostium-service`/`sing-box` processes, and embeds the Ostium icon.
- Generated Clash YAML was accepted by Mihomo 1.19.34 with `mihomo -t`; it
  contains fake-IP DNS, `ipv6: false`, and `GEOIP,CN,DIRECT,no-resolve`.
- Server IPv4-only failure reproduced: `curl -4` returned 200 for Google and
  Hugging Face, `curl -6` failed, while IPv4-only GitHub worked. Generated
  server config now uses `dns.strategy: ipv4_only` and
  `route.default_domain_resolver` to the internal `local` server; `sing-box
  check` accepts it.
- `0.1.8 -> 0.1.9` upgrade script: user, password material, subscription
  token, database, backup and `master.key` survive; a 0.1.8 backup restores.
- `0.1.9` install/reinstall/uninstall e2e passed; reinstall kept exactly one
  administrator.
- Publication verification: `scripts/verify-release.sh --version 0.1.9`
  downloaded all 23 assets, `sha256sum -c SHA256SUMS` passed, all five core
  platforms are present, build attestations verified, and PyPI reports
  `ostium-ctl==0.1.9`. The wheel and sdist SHA-256 values match between the
  GitHub Release and PyPI.
- Cross-directory backup restore (v2 streaming), missing-master-key rejection,
  checksum/tamper/truncation rejection and v1 backup import.
- Rule/RE2 validation, rule-set format validation, rule-set-only tester
  semantics and DNS pinning tests.
- First full review round: 40 findings closed, including commit-before-response,
  stats-outage quota enforcement, certificate path traversal, webhook secret
  encryption, Public UI recovery and release-workflow/Docker defaults. See
  `versions/V0.1.2_REVIEW_ROUND1.md`.
- Second full review round: 19 additional findings closed, including an
  apply-failure path that un-approved a committed inbound port, blocking DNS
  resolution on the event loop, a non-Public-UI certificate renewal switching
  the plaintext control plane to HTTPS, Public UI cookies without `Secure`,
  one-time credentials lost on a post-commit apply error, and release-checklist
  wording that still claimed no post-PyPI half-publication. See
  `versions/V0.1.2_REVIEW_ROUND2.md`.
- Release workflow ordering tests: draft release first, PyPI before GHCR/draft
  publication.
- Playwright/axe/visual regression: 73 passed against the built SPA and the
  current backend with one worker (1440/1024/390, dark/light, core-page axe,
  LCP/CLS and PWA checks). The visual snapshots are deterministic: the clock is
  frozen and every API path they render is mocked.
- Final pre-release review round: 13 P1 findings and one P2 fixed with tests
  that fail on `683ebf3` (core artifact body limit, split-user client watchdog,
  CLI disable/delete tombstones, export certificate resolution, certificate
  replacement recovery, subscription-refresh error persistence, installer
  reinstall and upgrade snapshots on Linux/macOS/Windows, validation-error
  serialization, coverage-gate stability). See `versions/V0.1.2_REVIEW_ROUND4.md`.
- 0.1.4 subscription layout fix (included): long URLs truncate inside the
  format cards using shrinkable grid tracks and a block-level URL element; a
  Playwright regression covers a 160-character token on desktop, tablet and
  mobile.
- 0.1.3 deployment and UI fixes (included): `/api/v1/system/info` survives
  `psutil.net_if_addrs()` raising `EAFNOSUPPORT` on VPS/container network
  stacks; first-install readiness uses the unauthenticated `/v1/health`
  endpoint; the collapsed sidebar header no longer overlaps the expand button;
  the Logs level filter keeps its width; release e2e scripts are executable and
  the sudo step preserves `PATH`. Added regression tests for these behaviors.

### Not verified in this workspace

These items require external hardware, accounts, runners or time. They are
**not** claimed as verified:

- Windows 11 runtime: setup, service, TUN/Wintun, PAC, SmartScreen, uninstall.
  The 0.1.9 server IPv4-only fix was validated by generated-config checks and
  user logs, but not by a full external Windows/server matrix. The 0.1.5/0.1.6/
  0.1.7 Windows failures were reproduced from user logs and `sc qc`, and the
  script changes were syntax-checked with PowerShell 7.7.
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

## Release decisions (D-111～D-115)

The release owner accepted the following in `versions/V0.1.2_DECISIONS.md`; the RC
evidence is in `versions/V0.1.2_RC_REPORT.md`:

- **D-111** PyPI-first ordering is accepted with the documented retry/yank/patch
  recovery; publication is not atomic.
- **D-112** Control-plane/core service isolation remains a 0.2.0 item.
- **D-113** The unit-only 75/65 coverage target is deferred; the repository and
  package gate at 94.29/90.44 is the release gate.
- **D-114** Linux is Tier 1; Windows/macOS are Tier 2 and published unsigned
  unless signing credentials are supplied.
- **D-115** Push, tag and publication require explicit release-owner approval.

## Release gates for 0.1.9

1. **Code and automation**: ruff, mypy, shellcheck, mkdocs strict, backend and
   frontend suites, real-core integration, coverage gates.
2. **Upgrade and data**: `0.1.8 -> 0.1.9` upgrade plus backup restore;
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
