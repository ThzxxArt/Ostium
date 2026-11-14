# Changelog

All notable changes are documented here. Format: Keep a Changelog; versioning:
SemVer.

## [0.1.1] - 2026-11-14

### Security

- Server admin UI now defaults to `127.0.0.1`; legacy `0.0.0.0` plaintext
  configurations are migrated unless `allow_insecure_bind = true` is set.
  `ostium serve` fails closed for non-loopback plaintext binds.
- Server egress now blocks RFC1918, CGNAT, the complete link-local range, cloud
  metadata (IPv4/IPv6) and SMTP port 25; `block_private_egress = false` keeps
  the SMTP block.
- Shadowsocks 2022 client passwords now use `server_key:user_key` in URI,
  Clash and sing-box formats.
- `/api/docs` and `/api/openapi.json` require an authenticated admin.
- Admin UI CIDR allowlist, WebSocket session revalidation, single-use local
  login tokens, password-change session revocation and expired login-limiter
  cleanup.
- TOTP enrollment uses a pending secret; cancel/close no longer locks out the
  administrator. TOTP failures count toward persistent lockout.
- Webhook SSRF protection with retries/HMAC; profile refresh blocks
  loopback/link-local/metadata targets while allowing LAN subscriptions.
- Rule-set path traversal fixed; rule match/regex/CIDR/reference validation;
  ruleset deletion checks references.
- Manual plaintext backup creation requires explicit acknowledgement; automatic
  daily backups are plaintext, include `master.key`, and are documented as such.
  Restore checks role, SQLite integrity and migrations. Certificate deletion
  removes key files after a successful apply; manual chains are verified;
  renewals keep the previous ready certificate.
- Windows core data/token/last-good moved to an admin/SYSTEM-only ACL directory;
  uninstall restores proxy/TUN state.

### Fixed

- Configuration apply restarts the child and verifies liveness; failures roll
  back and return 422/502 instead of pretending SIGHUP succeeded.
- Monthly quota reset commits; disabled users are retried if a core apply fails;
  final statistics flush on shutdown; quota thresholds 80/90% alert once.
- Retention policies execute for audit/traffic/jobs; automatic daily backups
  (default off, 7 kept, 0600) and `ostium update --check` are real.
- Subscription URLs use `public_base_url`/domain instead of request `Host`;
  tokens are not re-shown without an audited reveal; unknown formats return 400.
- Active profile persistence, profile reorder/activation, duplicate endpoint tag
  namespacing, real Clash API latency probes and per-inbound certificate
  selection.
- Startup runs Alembic `upgrade head`; newer schemas are rejected; restores run
  migrations with rollback.
- Inbound port conflicts return 409; skipped inbounds show their reason.
- Setup no longer offers unreachable Hysteria2/both without a certificate.

### Review round 2

- Client core uses an absolute `cache.db` path and writable working directories
  for systemd/launchd/Windows; the packaged client no longer fails at startup on
  a read-only root filesystem.
- API and core reject oversized chunked request bodies while streaming, before
  authentication/CSRF.
- Rule sets must be downloaded and verified locally before they can reach
  sing-box; remote rule-set URLs are no longer handed to the privileged core.
- `core install --manifest` rejects plaintext HTTP manifests.
- Settings, Public UI and inbound port changes publish only after validation and
  persist atomically; quota threshold alerts are committed; WebSocket honors the
  UI IP allowlist.
- Certificate renewals write a new generation and switch the database last;
  backup restore rolls back database, master key, config and certificates
  together.
- Hysteria2 obfs parameters, Trojan URI pins/`allowInsecure`, rule-set `format`,
  rule `protocol`/`source_port` and TUN MTU/stack now round-trip consistently
  across UI, subscriptions and core configuration.

### Delivery

- Release builds Windows setup, macOS DMG, Linux DEB/AppImage (amd64/arm64),
  Docker, SBOM and checksums from one tag; release publication refuses to
  overwrite existing assets.
- Release verification enforces frontend coverage, Playwright/axe/visual
  checks, shellcheck, PowerShell parsing, mkdocs `--strict`, dependency audits
  and the first-load JS budget; pull-request CI runs the Python/frontend gates.
- Windows/macOS installers are labelled unsigned when no signing certificate is
  configured; macOS notarization is optional and explicit.
- Documentation, migration guide and security advisory updated for the new
  defaults and residual external validation.

### Review round 1 (2026-11-14)

- Re-validate every redirect hop for subscription and rule-set downloads; direct
  loopback/link-local/metadata targets are rejected. Manual profile refresh
  failures now persist `last_refresh_error`.
- Monthly quota rollover now also re-enables users disabled by last month's
  quota; concurrent statistic flushes are serialised so stop/tick cannot
  double-count traffic.
- WebSocket sessions are revalidated on a timer even while events are flowing;
  revoked sessions stop reconnecting.
- Public UI enablement widens a loopback listener explicitly and remembers to
  restore it on disable; settings can now clear public base URL, ACME email and
  webhook secret.
- Certificate upload/self-signed issuance no longer overwrites explicit
  per-inbound assignments; expired certificates cannot be assigned. Rule-set
  create normalises names before duplicate checks and enabling an inbound checks
  TCP port conflicts.
- Backup restore snapshots through SQLite (WAL-safe) before migration, and
  archive extraction rejects `./../` traversal. Notification settings now gate
  webhooks; the update channel is honoured by `ostium update --check`.
- Localisation and accessibility fixes for login hero, error/empty/QR/chart
  components, command palette, settings navigation and backup labels.

### Review round 4 (pre-release)

- Normalised IPv4-mapped/6to4/Teredo/CGNAT addresses in SSRF checks and rejected
  HTTPS-to-HTTP redirect downgrades for subscriptions and rule sets.
- Hardened Linux/macOS installers: service-group creation, home-path validation,
  upgrade staging/rollback, database snapshots, user-UI restart and mode-switch
  cleanup. DEB now creates its service group explicitly.
- Windows core token/runtime ACL now grants only the installing user instead of
  the built-in Users group; Windows build failures and unsigned installers can
  no longer be silently published.
- Certificate deletion applies the new configuration before unlinking TLS
  material; failed applies retain the files used by the old last-good config.
- Fixed long proxy-user names overflowing endpoint tags, corrupt credentials
  breaking the subscriptions overview, rule-set file leaks, unbounded backup
  restore expansion and statistics epoch loss on failed commits.
- Frontend: subscription URLs in client setup, multi-condition rule editing,
  filtered batch selection, dashboard online/certificate/inbound truthfulness,
  auto endpoint display, keyboard-focusable log region, i18n/aria/timezone/scroll
  fixes.
- Release gates: branch coverage is measured, AppImage architecture/dependencies
  are correct and fail closed, Docker pushes wait for platform assets, and the
  release body comes from `RELEASE_NOTES.md`.

### Release status and blockers

- v0.1.1 is **published**: GitHub Release `v0.1.1`, PyPI `ostium-ctl==0.1.1`
  and GHCR tags `0.1.1`/`v0.1.1`/`latest` are live. Release assets are
  immutable; fixes go into the next patch release.
- The AppImage was built by the release workflow and published; the local review
  environment could not produce it (missing `file`/`appimagetool`) and is
  recorded as a local blocker, not as a successful local build.
- Windows 11, macOS 14, Nginx, Docker runtime, ACME, real TUN/LAN/DNS, 72h
  soak, performance, five-user usability and code signing remain external
  blockers; they are not claimed as verified.

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

### Review round 3 (2026-11-14)

- Linux client systemd units no longer double-substitute `/var/lib/ostium-core`
  or rewrite `/etc/ostium/client.toml` into the data directory; default and
  custom-path renders are covered by an executable regression test.
- Enabled TLS inbounds can no longer be unbound by sending only
  `certificate_id: null`; an explicit disable is required first.
- CLI one-time subscription tokens are printed before a core apply that may
  fail, so an unavailable core no longer destroys the only copy.
- Subscription YAML alias expansion and deeply nested JSON are bounded; an
  unknown response charset falls back to UTF-8 instead of returning 500.
- Core logs are truncated while running and read from a bounded tail; statistics
  flush preserves deltas sampled during the database commit.
- Session expiry now clears the local auth state before redirecting to login,
  eliminating the authenticated-route redirect loop.
- Server routing rules are explicitly documented as local-only in v0.1.1; the
  API and UI no longer claim they are distributed through subscriptions.
- Client home shows the configured mixed port and activates the selected
  profile; system-proxy reconnect restores the OS proxy, and a failed proxy
  restoration leaves the core running instead of silently breaking networking.
- Release DEB versions strip the `v` tag prefix; upgrade health checks read the
  existing Public UI/port; macOS honours `--no-start`; purge removes per-user
  client data.
- Rule sets require HTTPS, writes are fsynced/atomic, profile endpoint choices
  are validated, and reverse-proxy requests no longer gain loopback privileges.
- Exported profiles/diagnostics are 0600 on POSIX; ACME directory URLs must use
  HTTPS; connection IDs are URL-encoded before reaching the Clash API.

### Known boundaries

- No NaiveProxy, standalone kill switch, native mobile app, multi-node server
  orchestration, RBAC, DNS-01/TLS-ALPN-01 or silent auto-update.
- UI downtime pauses quota enforcement; the tunnel continues.
- Unsigned Windows/macOS installers may trigger SmartScreen/Gatekeeper.
