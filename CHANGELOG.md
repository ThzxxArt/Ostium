# Changelog

All notable changes are documented here. Format: Keep a Changelog; versioning:
SemVer.

## [0.1.0] - 2026-11-13

### Release

- Published GitHub Release `v0.1.0`, PyPI `ostium-ctl==0.1.0` and GHCR tags
  `0.1.0`/`v0.1.0`/`latest`.
- Post-release live-download testing fixed the online installer's checksum
  lookup; the Release `install-online.sh` and `SHA256SUMS` assets were repaired
  on `main` commit `8e3bb41`.

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
- Client Allow LAN: exposes the mixed proxy on `0.0.0.0:7890` for trusted LAN
  devices, with the Network page showing local addresses and an explicit
  no-authentication warning.
- Aurora Console Web UI: dark/light themes, command palette, shortcuts, PWA,
  responsive layouts, first-run wizards, live logs/connections/jobs, accessible
  components and visual regression hooks.
- CLI for init/serve/core/users/profiles/backup/cert/proxy/TUN/diagnostics.
- Backups with scrypt + AES-256-GCM, staged restore, upgrade/rollback tooling.
- systemd/launchd/Windows service assets, Linux installer, Docker image,
  GitHub Actions CI, core build, security scans and release automation.
- One-click online installer for Linux/macOS and PowerShell installer for
  Windows: downloads static uv, managed Python 3.13, wheel, core and checksums;
  supports install/upgrade/uninstall/status and needs no system Python.
- Installer modes `--run-as-root` (no service users, both services as root) and
  `--no-service` (OpenRC/runit/s6/supervisord/manual).
- Chinese documentation for every guide and reference, including one-click
  install and service-manager guides; English README remains available.
- Documentation for deployment, client, TUN, ACME, subscriptions, API, CLI,
  backups, upgrades, troubleshooting and the design system.
- Comprehensive audit and coverage suite: 419 backend tests, 137 frontend tests
  and 21 Playwright tests, with per-module coverage gates and six committed
  dark/light visual baselines.

### Fixed

- Release installers now install from a flat release-asset directory, verify the
  sdist, and never execute an unverified GitHub source archive.
- systemd state/ruleset directories live under the data directory, so
  `ProtectHome`/`ProtectSystem` no longer prevent services from starting.
- Default non-root server installs chown the SQLite database and master key to
  the service user after initialisation.
- Public admin UI cannot be enabled during first install, and `serve` refuses to
  start without TOTP plus an unexpired certificate.
- Inbound ports are editable; `proxy_ports` is persisted and the core reloads
  the whitelist before every apply, enabling Nginx 443 + Reality 9443.
- Core tokens are only created by the privileged core; the UI never mints its
  own token and reports `core_unavailable` instead.
- `SHA256SUMS` and all release assets use flat basenames, matching GitHub
  Release downloads; core `.sha256` files are download-friendly.
- System proxy enable/disable now records recovery state before touching the
  desktop and rolls back per-key on partial failure.
- `ostium core install --url` requires SHA-256 and accepts a `.tar.gz` core
  archive; downloaded core checks no longer install unverified bytes.
- Local login links are loopback-only; config saves are atomic and persist
  `state_dir`/`core_token_file`.
- macOS uninstall is no longer blocked by the server-role check, custom prefix
  plists are rendered correctly, and the UI documents the required re-login.
- Release bundles include LICENSE/NOTICE and the core SBOM; Windows/macOS
  bundles no longer omit license files.
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
- Client config saves now return to the exact loaded file (`client.toml`, UI
  config, or `config.toml`) instead of a generic path; UI and core configs are
  separated on Linux and macOS.
- API tokens now enforce their documented `read`/`write` scopes.
- TOTP recovery codes are single-use and can be entered from the login page.
- Allow LAN changes roll back and return `502` if sing-box cannot be applied;
  TUN mode rejects LAN sharing.
- Trusted proxy client IPs use the last `X-Forwarded-For` hop; the Nginx sample
  overwrites the header with `$remote_addr`.
- Installer upgrades use a new venv with atomic switch and rollback; dangerous
  `--prefix`/`--purge` roots are rejected.
- Client core token paths now consistently use `runtime/core.token`; Linux
  client UI and core configs no longer overwrite each other.
- macOS client installs no longer create an unusable administrator before the
  setup wizard; launchd UI config/token/group handling was corrected.
- Windows installer no longer copies its install directory onto itself;
  checksum matching handles nested `./windows/...` paths.
- Core release archives use `sing-box.exe` on Windows; manifest URLs point at
  the Ostium release tag instead of the sing-box version.
- Docker includes the built SPA and grants bind capability to both Python and
  sing-box; `.dockerignore` keeps local data out of the build context.
- Logs redact UUIDs, certificate domains reject path separators, and the
  nightly workflow runs a real config-generation/validation smoke instead of a
  placeholder.
- GitHub Actions updated to current major versions (Node 24-era actions and
  CodeQL v4).
- Replaced `vite-plugin-pwa`/`workbox-build` with a small in-repo service
  worker generator and added npm overrides; full `npm audit` is now 0
  vulnerabilities, and PWA registration is covered by Playwright.
- Third audit: Allow LAN now passes through the privileged core validator and
  survives a core restart; TUN and Allow LAN are mutually exclusive.
- Third audit: Linux upgrades rewrite pip console-script shebangs after the
  atomic venv rename, so `ostium`/`pip` keep working after `--upgrade`.
- Third audit: Windows release bundles the full PyInstaller service directory,
  stores the LocalSystem core config and binary under `%ProgramFiles%`, and
  avoids self-copies during the release build.
- Third audit: PyPI publishing stages only the wheel/sdist, and release jobs
  use scoped permissions; Docker bakes the actual release version.
- Third audit: subscription responses support Unicode user names, Windows PAC
  settings are restored, and the PWA cache key now hashes asset contents.
- Third audit: KDE proxy state is restored/removed correctly, the client core
  config is read-only to the UI group, and tag releases now run a `verify`
  job before Docker/PyPI/GitHub publication.

### Known boundaries

- No NaiveProxy, standalone kill switch, native mobile app, multi-node server
  orchestration, RBAC, DNS-01/TLS-ALPN-01 or silent auto-update.
- UI downtime pauses quota enforcement; the tunnel continues.
- Unsigned Windows/macOS installers may trigger SmartScreen/Gatekeeper.
