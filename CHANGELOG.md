# Changelog

All notable changes are documented here. Format: Keep a Changelog; versioning:
SemVer.

## [0.1.0] - unreleased

### Added

- PyPI distribution `ostium-ctl` (import/CLI remains `ostium`).
- Dual-role Ostium app (server/client) with one Python package, SPA, CLI and
  installer.
- `ostium.service` control plane and `ostium-core.service` privileged core
  supervisor with a loopback token API, role whitelists and atomic rollback.
- Pinned sing-box 1.14.4 custom build (`with_v2ray_api`, no Naive outbound).
- Server: Reality, Hysteria2, Trojan, Shadowsocks 2022; multi-user credentials,
  quotas, expiry, subscription tokens, four subscription formats and QR codes.
- Per-user V2Ray traffic accounting with epoch reset handling, daily aggregates
  and automatic quota/expiry enforcement.
- ACME HTTP-01, manual certificate upload and self-signed certificates with
  renewal, assignment and expiry alerts.
- Client: mixed proxy, Windows/macOS/Linux system proxy, TUN with strict route,
  smart/global/direct/custom routing, FakeIP DNS, URLTest failover, multi-profile
  subscriptions, QR import and diagnostics.
- Aurora Console Web UI: dark/light themes, command palette, shortcuts, PWA,
  responsive layouts, first-run wizards, live logs/connections/jobs, accessible
  components and visual regression hooks.
- CLI for init/serve/core/users/profiles/backup/cert/proxy/TUN/diagnostics.
- Backups with scrypt + AES-256-GCM, staged restore, upgrade/rollback tooling.
- systemd/launchd/Windows service assets, Linux installer, Docker image,
  GitHub Actions CI, core build, security scans and release automation.
- Documentation for deployment, client, TUN, ACME, subscriptions, API, CLI,
  backups, upgrades, troubleshooting and the design system.
- Comprehensive audit and coverage suite: 384 backend tests, 132 frontend tests
  and 18 Playwright tests, with per-module coverage gates and six committed
  dark/light visual baselines.

### Fixed

- Local one-time login tokens no longer fail intermittently when the binary
  signature contains a `.` byte.
- Failed login counters and audit entries are persisted before the error
  response, restoring account lockout and failed-login auditing.
- Setup now requires CSRF, matching every other cookie-authenticated mutation.
- Diagnostics redaction handles quoted JSON keys, so tokens/passwords cannot
  leak through `/system/diagnostics`.
- Timezone-naive SQLite timestamps are normalised before expiry, quota and
  certificate comparisons across users, stats, doctor, housekeeping and ACME
  renewal.
- Duplicate usernames now return `409 name_taken` instead of a 500.
- Invalid or corrupted profile subscriptions return controlled `ProfileError`
  responses instead of 500s.
- Backups with a wrong password return `400 invalid_password`; staged restores
  validate the password immediately instead of silently failing at restart.
- The Web UI now parses `application/problem+json`, preserving `code`/`detail`
  for TOTP, rate-limit and validation errors.
- CLI URL profile imports retain their subscription URL so `profile refresh`
  works.
- `python-multipart` upgraded to 0.0.31 (security advisories).
- Mobile viewport aligned to 390px; visual baselines and light theme added.
- Removed dead quota-flush branch and fixed docs/nav/shellcheck issues.

### Known boundaries

- No NaiveProxy, standalone kill switch, native mobile app, multi-node server
  orchestration, RBAC, DNS-01/TLS-ALPN-01 or silent auto-update.
- UI downtime pauses quota enforcement; the tunnel continues.
- Unsigned Windows/macOS installers may trigger SmartScreen/Gatekeeper.
