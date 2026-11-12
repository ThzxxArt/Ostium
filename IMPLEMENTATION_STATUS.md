# Ostium v0.1.0 implementation status

Updated: 2026-11-12

Legend: `[x]` implemented and exercised locally, `[~]` implemented but needs
platform/external validation, `[ ]` not done yet.

## Delivered in this workspace

### Backend and data plane

- [x] Python 3.13 package `ostium-ctl`, import/CLI `ostium`, GPL-3.0-or-later.
- [x] FastAPI control plane with lifespan-managed SQLAlchemy/aiosqlite engine.
- [x] SQLite schema, WAL/foreign keys, Alembic initial migration, create/stamp
      bootstrap.
- [x] Argon2id admin, sessions, TOTP, recovery-code display, API tokens, CSRF,
      Origin/Host checks, security headers, login throttling.
- [x] AES-256-GCM field encryption with AAD, master key 0600, scrypt encrypted
      backups.
- [x] Two-service core: `core-run` minimal API, bearer token, 2 MiB limit,
      role/port/path whitelist, `sing-box check`, atomic last-good, SIGHUP reload
      (restart on Windows), log capture.
- [x] Server config generation: Reality, Hysteria2, Trojan, SS2022, V2Ray stats,
      Clash API, egress blocks.
- [x] Client config generation: mixed, TUN, smart/global/direct/custom routing,
      FakeIP DNS, URLTest, selector, cache file.
- [x] Two-service IPC validated end-to-end: EngineManager → `/v1/apply` →
      `sing-box check` → supervisor start; V2Ray gRPC and Clash API listeners
      came up on the custom core, with the UI showing Connected.
- [x] Real sing-box 1.14.4 config checks and a local Reality loopback traffic
      test (curl → client mixed → server Reality → example.com).
- [x] Users, credentials, quotas, expiry, subscription tokens, token rotation.
- [x] Custom `with_v2ray_api` core built with Go 1.25.5 (version
      `1.14.4-ostium.1`); gRPC per-user counters verified live
      (`alice: (5679, 19387)` after test traffic) and Clash API verified.
- [x] V2Ray stats collector epoch/quota logic, including a live end-to-end
      test with the custom core, a real client, real loopback traffic and a
      real collector tick (`test_collector_live.py`).
- [x] Four subscription formats + QR + share URIs + public rate limiting.
- [x] ACME HTTP-01 client (account key, order, challenge server, CSR, finalize)
      and self-signed/manual certificate storage; live ACME not run here.
- [x] System proxy adapters for Windows, macOS, GNOME and KDE; env hint.
- [x] Backups: SQLite online backup, master key/config/certs, scrypt+AES-GCM,
      staged restore, pending restore applied before DB open.
- [x] Jobs, events/WebSocket, audit, alerts, webhook helper, Prometheus text.
- [x] System info/doctor/diagnostics, service status/reload, TUN/proxy/mode API.
- [x] Profiles: JSON/Base64/URI/Clash/sing-box import, refresh, endpoint select,
      QR image scanning in the UI.
- [x] Rules CRUD/reorder/test and remote rule-set update with atomic replace.
- [x] CLI: init/serve/core-run/status/open/logs/doctor/connect/disconnect/proxy/
      tun/update/diagnostics/user/profile/core/backup/cert/service.
- [x] Alembic environment + initial migration verified on a temp database.

### Frontend (Aurora Console)

- [x] Vue 3 + TypeScript + Vite + Naive UI, self-hosted Inter, Lucide icons,
      tokenized dark/light themes.
- [x] App shell: 248px/76px sidebar, topbar status pill, search, jobs,
      notifications, theme/language, user menu, mobile drawer + bottom nav.
- [x] Pages: setup, login, dashboard, inbounds, users, subscriptions,
      connections, routing (server/client), certificates, logs, jobs, system,
      audit, settings, client home, profiles, network, stats, diagnostics,
      onboarding, 404.
- [x] First-run server 4-step and client 3-step wizards.
- [x] Command palette (Cmd/Ctrl+K) with Fuse search, recents and keyboard nav.
- [x] Shortcuts (`G` sequences, `C`, `/`, `?`, `Esc`), bulk user actions,
      skeletons/empty/error states, QR modals, copy feedback.
- [x] PWA manifest/service worker, generated brand icons/favicon.
- [x] Lazy-loaded ECharts chart wrapper to keep echarts out of the initial
      render path.
- [x] Responsive breakpoints and reduced-motion handling.
- [x] Browser notifications and PWA update prompt are wired; permission is
      opt-in from Settings, with denied/unsupported/fallback paths tested.
- [x] Visual regression baselines committed for 1440/1024/390 in dark and light
      themes; axe smoke and no-horizontal-scroll checks run on all three.
- [x] 132 Vitest tests and 18 Playwright tests pass; see `AUDIT_REPORT.md`.

### Packaging, CI and docs

- [x] `scripts/build-core.sh` (pinned Go/tags/SBOM/sha256), manifest generator.
- [x] systemd server/core/client units, user unit, launchd plists and macOS
      install script.
- [x] Linux server/client installer, Windows PowerShell install/uninstall,
      Inno Setup script, Windows pywin32 service wrapper.
- [x] Dockerfile (web/core/runtime stages), entrypoint, compose example.
- [x] CI, core build, security, release, docs, e2e and nightly workflows.
- [x] MkDocs site, server/client/TUN/ACME/subscription/UI guides, CLI/API/profile/
      ports references, backup/upgrade/troubleshooting, threat model, design
      system and UX docs.
- [x] README, LICENSE, NOTICE, SECURITY, CONTRIBUTING, CHANGELOG.

## Test status

- `ruff check` / `ruff format --check`: pass (132 files).
- `mypy src/ostium` strict: pass (69 source files).
- `pytest`: 385 passed, 0 skipped, 0 failed, including real sing-box config
  checks, core apply/stop/rollback, the custom `with_v2ray_api` core, a live
  client → Reality → collector traffic test, certificates, jobs, auth, backups,
  stats, client profiles, rules, ACME challenge server and API flows.
- Backend coverage: statements 98.54%, branches 95.84%; every module ≥85% and
  `api/core/services/engine` ≥90% (enforced by `scripts/coverage_gate.py`).
- `npm run lint`, `typecheck`, `test`, `build`, `format:check`: pass.
- Frontend coverage: statements 91.84%, branches 85.97%, functions 89.39%,
  lines 92.59% (Vitest v8, thresholds 85).
- Playwright: 18 passed on desktop 1440, tablet 1024 and mobile 390; login,
  dashboard, command palette, axe smoke, no-horizontal-scroll and six dark/light
  visual baselines pass.
- `pip-audit` and `npm audit`: no known vulnerabilities.
- `mkdocs build --strict`, `shellcheck`, clean-wheel install and serve smoke:
  pass.
- Real ACME, Windows/macOS TUN, Windows service, macOS launchd, Windows/macOS
  system proxy, 72h soak, usability tests and installer-on-fresh-VM are not
  run in this environment; see `MANUAL_TASKS.md`.

## Design deviations / ADRs

- TypeScript 7.0.2 is not compatible with `vue-tsc` (it resolves the removed
  `typescript/lib/tsc` path). v0.1.0 uses TypeScript 6.0.3 and vue-tsc 3.3.14.
  See `docs/adr/0001-typescript-6.md`.
- The official sing-box 1.14.4 release lacks `with_v2ray_api`; per-user stats
  require `scripts/build-core.sh`. The custom build was compiled and its gRPC
  stats were verified locally with two test users and live traffic.
- Default smart routing uses an offline curated domain-suffix list, not remote
  GeoIP/GeoSite downloads, so first start does not depend on GitHub reachability.
  Users can add remote rule sets explicitly.
- The UI uses `create_all` + an Alembic stamp for the initial schema and ships
  the initial migration; future schema changes use Alembic.

## Release blockers still open

- [ ] Run TUN + system proxy acceptance on real Windows 11 and macOS 14, and
      Linux TUN on a privileged host.
- [ ] Run ACME staging and one production issuance on the Hong Kong server.
- [ ] Run a fresh Ubuntu 24.04 installer test and a backup/restore/upgrade drill.
- [ ] Run 72h soak, performance budgets, and the 5-user usability test.
- [ ] Code signing/notarization (optional per PLAN, but SmartScreen/Gatekeeper
      warnings remain).
- [ ] Complete the account/release steps in `MANUAL_TASKS.md` (GitHub, PyPI,
      GHCR, signing) after explicit approval.

The full evidence, per-file audit and residual-risk list is in
[`AUDIT_REPORT.md`](AUDIT_REPORT.md).
