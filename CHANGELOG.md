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

### Known boundaries

- No NaiveProxy, standalone kill switch, native mobile app, multi-node server
  orchestration, RBAC, DNS-01/TLS-ALPN-01 or silent auto-update.
- UI downtime pauses quota enforcement; the tunnel continues.
- Unsigned Windows/macOS installers may trigger SmartScreen/Gatekeeper.
