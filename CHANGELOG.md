# Changelog

All notable changes are documented here. Format: Keep a Changelog; versioning:
SemVer.

## [0.1.12] - 2026-11-18

### Fixed

- Windows clients no longer leave a dead TUN route behind after a crash or a
  forced stop. The supervisor now stops sing-box with `CTRL_BREAK_EVENT`, and
  the privileged core removes stale `Ostium`/`ostium0`/`sing-box` routes and
  adapters on startup and after a TUN session. This fixes the "connect once,
  then TCP to the server times out until reboot/uninstall" failure.
- Client TUN configs default to `strict_route: false` on Windows. sing-box
  implements strict routing with WFP filters there; a hard kill can skip their
  cleanup and blackhole outbound TCP. Ostium has no firewall-level kill switch,
  so the extra WFP risk is not worth it.
- Windows system-proxy status now checks the live WinINET registry instead of
  trusting the state file. If another client rewrites `ProxyEnable`,
  `ProxyServer` or `AutoConfigURL`, Ostium reports `stale`, re-applies on the
  next connect, and the watchdog takes the proxy back while connected.
- Changing `mixed_port` now moves an enabled system proxy to the new port in the
  same request instead of leaving the browser pointed at a closed listener.
- The generated client DoH remote now includes `path` and
  `tls.server_name`, not just a bare server IP.
- The dependency audit gate now uses an exact GHSA allowlist with an expiry
  date. The only current entry is the unfixed dev-only `picomatch`
  ReDoS advisory; any other vulnerability still fails.

### Documentation

- Added the 0.1.11 -> 0.1.12 upgrade guide and the Windows stale-TUN repair
  steps.

## [0.1.11] - 2026-11-17

### Added

- Deterministic build/runtime provenance: `ostium version --json`,
  `/api/v1/system/provenance`, Web `build.json` and `/system/port-owners`.
- Layered diagnostics for version consistency, listener ownership, configuration
  drift, core readiness, DoH comparison, direct/proxy TLS egress, system proxy,
  TUN and disk usage, plus `/system/selftest` and grouped UI.
- Server DNS policy: `server_dns_mode` (`auto`/`doh`/`udp`) and
  `server_dns_doh_url`; startup DoH probe with explicit UDP fallback.
- Client policy `system_proxy_fail_open` / `system_proxy_fail_open_seconds`
  (default 45 s) with critical alert and automatic proxy restoration.
- Configurable `stats_online_window_seconds` and live per-user traffic timestamps.

### Changed

- `CONFIG_POLICY_VERSION` is now `3`; one DNS server is generated instead of an
  unreferenced second entry. DoH is preferred; UDP is an explicit fallback.
- Online means "traffic observed within the window", not a TCP connection count.
  Rates decay to zero after two quiet ticks and during a stats outage.
- Installers assert the expected version and port ownership instead of accepting
  any HTTP 200; Windows refuses to stop an unknown process on the UI port.
- Web UI: Ctrl/Cmd+C no longer toggles the connection, login refresh is
  re-entrant-safe, warn/fail counts are separate, `applied=false` shows a warning,
  TUN availability is real, certificate expiry labels are accurate and table rows
  are keyboard accessible.

### Fixed

- Removed the dead `local2` DNS entry and every hardcoded `223.5.5.5` default,
  including the Clash subscription template.
- Windows system-proxy restoration recognises a lost state file when WinINET
  still points at Ostium's own mixed port.
- Stale version data in the login screen and status poll race.

### Documentation

- Added the 0.1.10 -> 0.1.11 upgrade, DNS, fail-open and rollback guide.

## [0.1.10] - 2026-11-16

### Fixed

- Server-side sing-box no longer uses `223.5.5.5` as its outbound resolver.
  On the deployed server that resolver returned Facebook/Twitter addresses for
  Google and Hugging Face, which accepted TCP but failed TLS; GitHub happened
  to resolve correctly. Use the public resolvers `8.8.8.8` and `1.1.1.1` with
  the existing `ipv4_only` strategy.

### Documentation

- Added the 0.1.9 -> 0.1.10 server DNS and client-version verification guide.

## [0.1.9] - 2026-11-16

### Fixed

- Server-generated sing-box configurations now use `dns.strategy: ipv4_only`
  and route outbound domain resolution through the internal `local` resolver.
  On an IPv4-only VPS, Google and Hugging Face were resolved to AAAA, the
  direct outbound timed out, and clients saw a TLS handshake failure while
  IPv4-only GitHub worked.

### Documentation

- Added the 0.1.8 -> 0.1.9 IPv4-only server upgrade and IPv6 port notes.

## [0.1.8] - 2026-11-16

### Fixed

- The generated Windows UI launcher (`ostium-ui.ps1`) no longer uses
  `ErrorActionPreference=Stop`. Uvicorn writes normal startup INFO lines to
  stderr; PowerShell treated them as terminating errors and killed the UI child,
  leaving 8787 without a listener even though `OstiumCore` was running. The
  launcher now uses `Continue` and checks the process exit code.

### Documentation

- Added the 0.1.7 -> 0.1.8 Windows reinstall and PWA-cache guide.

## [0.1.7] - 2026-11-16

### Fixed

- The frozen Windows service now enters `StartServiceCtrlDispatcher` when SCM
  starts it with no arguments. Previously `win32serviceutil.HandleCommandLine`
  treated the empty argument list as a usage request and exited, so SCM waited
  for a dispatcher and reported error 1053. Interactive commands such as
  `debug`, `install` and `remove` still use `HandleCommandLine`.
- Interactive Windows installs now show the final service step in a visible
  PowerShell console, with the same lines written to `install.log`. Silent
  installs remain hidden.

### Documentation

- Added the 0.1.6 -> 0.1.7 Windows reinstall and service-log guide.

## [0.1.6] - 2026-11-16

### Fixed

- The Windows UI and service bundles now include `aiosqlite`. SQLAlchemy imports
  the async SQLite DBAPI dynamically, and the frozen apps previously exited
  during FastAPI lifespan startup with `ModuleNotFoundError`.
- The Windows service reaches the SCM dispatcher before importing FastAPI,
  uvicorn and the core app. This removes the 30-second `1053` startup timeout on
  machines where the frozen bundle's import takes longer than the SCM window.
- Reinstalling stops orphan `ostium-service` and `sing-box` processes that could
  hold port 8788 and make the replacement service exit immediately.
- The Windows installer no longer aborts UI setup when `OstiumCore` fails to
  start. It registers and starts the UI task anyway, writes the service failure
  and `sc.exe qc` output to `%ProgramData%\Ostium\logs\install.log`, and reports
  the core as degraded. This keeps `http://127.0.0.1:8787` reachable for
  diagnostics instead of leaving a connection-refused page.
- The Windows service writes startup/exception details to
  `%ProgramData%\OstiumCore\logs\service.log` and redirects uvicorn output
  there, so a service that stops immediately leaves a trace instead of only a
  generic SCM error.
- The Windows setup and both executables now embed the Ostium app icon.

### Documentation

- Added the 0.1.5 -> 0.1.6 Windows reinstall and service-diagnostic guide.

## [0.1.5] - 2026-11-16

### Fixed

- The login page now reads `login_totp_required` from the unauthenticated
  `/api/v1/auth/status` response and shows the verification-code field on the
  first render. A password-only login no longer consumes a failed-attempt slot
  or counts toward the account lockout; only a supplied-but-wrong TOTP or
  recovery code does.
- The Windows installer starts the UI through a hidden PowerShell wrapper
  instead of handing a `.cmd` file to Task Scheduler, writes startup output to
  `%ProgramData%\Ostium\logs\ui.log`, waits for `/healthz` on port 8787 before
  reporting success, and adds the install directory to the machine `PATH` so
  `ostium` works in a new terminal. Uninstall removes the PATH entry.
- Third-party Clash subscriptions now use a fake-IP DNS resolver and a
  `no-resolve` GEOIP rule. This prevents a polluted system DNS answer from
  matching `GEOIP,CN` and sending Google, YouTube or Hugging Face DIRECT while
  GitHub happens to resolve to a non-CN address.

### Documentation

- Added the 0.1.5 TOTP, Windows startup/PATH and Clash subscription
  troubleshooting notes; refreshed install examples and test counts.

## [0.1.4] - 2026-11-15

### Fixed

- Long subscription URLs no longer overflow the format cards on the
  Subscriptions page. The two-column grid now uses shrinkable tracks, the URL
  is a block element so ellipsis applies, and card headers truncate long names.
  A Playwright layout regression covers a 160-character token on desktop,
  tablet and mobile.

## [0.1.3] - 2026-11-15

### Fixed

- The collapsed sidebar no longer places the expand button on top of the brand
  mark; the logo and toggle stack vertically inside the 76 px rail.
- The Logs page level filter keeps a stable 130 px width instead of shrinking
  to a single visible letter in the toolbar flex row.
- The dashboard no longer returns `500 internal server error` on VPS or
  container network stacks where `psutil.net_if_addrs()` raises
  `EAFNOSUPPORT`. LAN address hints are optional and no longer take down
  `/api/v1/system/info`.
- A fresh server install no longer reports "core is not running" when the core
  is healthy. The readiness check uses the unauthenticated `/v1/health`
  endpoint instead of the bearer-token-protected `/v1/status`.
- Release e2e scripts are committed with the executable bit and invoked through
  `bash`; the sudo install step preserves `PATH` so `uv` remains available.

### Documentation

- Version-iteration plans, decisions, audits and review ledgers moved to
  `versions/`; README, CHANGELOG, RELEASE_NOTES and SECURITY remain at the
  repository root for the release workflow and preflight.
- Release status, badges and upgrade notes updated for 0.1.3.

## [0.1.2] - 2026-11-15

### Fixed

- Quota/expiry apply failures no longer clear pending revocations; the core
  strips revoked users from `last-good` on startup and the control plane
  reconciles the running configuration with the database.
- The server core refuses a `last-good` file generated by an older security
  policy instead of silently running the old egress rules after an upgrade.
- Backup format v2 includes rule sets and the ACME account key, verifies member
  checksums, rewrites certificate/rule-set paths, refuses a missing
  `master.key` for encrypted databases, and clears stale runtime configuration
  after restore.
- Public UI certificate renewal reloads TLS; expired certificates start a
  loopback recovery console. Public UI 8443 subscription URLs include the port.
- `/auth/status` failures show a retryable error page and no longer redirect an
  existing installation to `/setup`.
- User quota edits preserve exact byte counts; rule edits cannot silently drop
  conditions; subscription requests cannot cross users; logs filter on the
  server and stop forcing scroll on new records.
- Rule-set-only rules are reported as unknown rather than matching everything;
  RE2-incompatible regex syntax is rejected; outbound HTTP fetches pin the
  validated DNS address.
- Windows installer removes inherited `ProgramData` access, protects the UI
  database and `master.key`, and stops the core service before replacing files.
- The release workflow creates and verifies a draft release before publishing
  PyPI, then promotes GHCR tags; installers follow `latest` instead of a
  hardcoded previous version.

### Review round 1 (2026-11-15)

- Admin/API mutations now commit before the response is sent; a failed commit
  returns an error instead of reporting success.
- Quota/expiry enforcement still runs when V2Ray statistics are unavailable and
  raises a critical alert after a sustained outage.
- Startup refuses to generate a replacement `master.key` when an existing
  database contains encrypted fields.
- Webhook delivery and Reality preflight pin the validated DNS addresses;
  webhook secrets are encrypted at rest.
- Backup v2 streams encryption/decryption, rejects path traversal, and refuses
  to create a backup that omits the key for encrypted data.
- Rule-set downloads validate the SRS/source format; rule tests are bounded.
- Public UI recovery restores the original listener and secure-cookie policy;
  explicit Disconnect is persisted across restarts.
- Frontend auth recovery, subscription/user-detail races, rule-condition
  preservation, error states, Public UI restart warnings and coverage gates
  were corrected.
- Release workflow no longer overwrites published assets, provides the core to
  install/upgrade e2e jobs, and Docker defaults the admin UI to loopback.

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
