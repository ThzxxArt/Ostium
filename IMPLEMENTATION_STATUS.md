# Ostium v0.1.1 implementation status

Updated: 2026-11-14

Legend: `[x]` implemented and exercised locally, `[~]` implemented but needs
platform/external validation, `[ ]` not done yet.

## v0.1.1 delta

- [x] Default admin bind is loopback; legacy `0.0.0.0` plaintext configs migrate;
      `serve` fails closed without `allow_insecure_bind`.
- [x] Server egress blocks RFC1918/CGNAT/link-local/metadata/SMTP 25; verified
      with a real `sing-box check`.
- [x] SS2022 multi-user `server_key:user_key` validated by a real loopback
      traffic test.
- [x] Apply restarts and verifies the child; failures roll back and return
      422/502.
- [x] TOTP pending/confirm/cancel; docs authentication; UI IP allowlist;
      WebSocket revalidation; single-use local login; password-change session
      revocation.
- [x] Rule/path/reference validation, profile activation/reorder, duplicate tag
      namespacing, per-inbound certificates, certificate renewal retention.
- [x] Alembic `upgrade head` at startup, fresh/legacy/newer-version handling,
      restore + migration rollback.
- [x] Auto backup/retention, quota retry/commit/alerts, job recovery, update
      check, subscription public base URL and audited reveal.
- [x] Windows/macOS package scripts, Linux DEB/AppImage builder, Docker hardening,
      release provenance/SBOM scaffolding.
- [~] Windows/macOS/Docker/Nginx/ACME/TUN/72h/performance/5-user and code signing
      remain external validation; see `MANUAL_TASKS.md`.
- [x] Local final gates (review round 2): 523 regular backend tests + 10 real
      sing-box integration tests, 95.3%/91.5% coverage; 160 frontend tests,
      90.6%/85.1% coverage; 69 Playwright cases (axe/visual/performance/PWA);
      ruff/mypy/shellcheck/mkdocs/pip-audit/npm audit green.
- [x] Review round 2 fixed 31 additional findings (9 P1, 22 P2), including the
      read-only client-core cache path, pre-auth chunked body limit, rule-set
      remote fetch boundary, certificate generation switching and backup
      file-level rollback. See `V0.1.1_REVIEW_ROUND2.md`.
- [x] Review round 3 revalidated R1/R2 and fixed 36 additional findings
      (6 P1, 30 P2): Linux unit path rendering, enabled TLS inbound unbinding,
      CLI one-time tokens, subscription alias/JSON limits, 401 redirect loop,
      running-core log limits, statistics pending races, release DEB version,
      upgrade health checks, reverse-proxy loopback semantics and frontend
      contract/warning gaps. See `V0.1.1_REVIEW_ROUND3.md`.
- [x] Review round 4 revalidated R1/R2/R3 and fixed additional pre-release
      findings across SSRF normalisation, installer lifecycle/path safety,
      DEB/service accounts, Windows token ACLs, AppImage build/architecture,
      release gating, certificate deletion order, backup resource bounds,
      frontend setup/rules/dashboard/i18n/session paths and docs truthfulness.
      See `V0.1.1_REVIEW_ROUND4.md`.
- [x] Local final gates (review round 4): 585 regular backend tests + 10 real
      sing-box integration tests; 173 frontend tests; 69 Playwright cases;
      coverage gates green; first-load JS 193.4 KiB gzip.

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
      role/port/path whitelist, `sing-box check`, atomic last-good, restart +
      liveness verification with rollback, log capture.
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
- [x] 137 Vitest tests and 21 Playwright tests pass; see `AUDIT_REPORT.md`.
- [x] Second audit fixed client token/config paths, API token scopes,
      recovery-code login, Allow LAN rollback, installer upgrade rollback,
      Windows/macOS installer paths, Docker SPA assets, core manifest URLs and
      CI action versions (see `AUDIT_REPORT.md` §12).
- [x] Third audit fixed Allow LAN through the core validator, the broken Linux
      upgrade shebangs, Windows service packaging/SYSTEM config boundaries,
      PyPI staging, Unicode subscription filenames, PWA content hashing,
      TUN/Allow LAN exclusion and Windows PAC restoration (see §13).

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

- `ruff check` / `ruff format --check`: pass (149 files).
- `mypy src/ostium` strict: pass (71 source files).
- `pytest -m "not integration"`: 585 passed, 0 skipped, 0 failed.
- Real sing-box integration: 10 passed, 0 skipped.
- Backend coverage: statements 94.95%, branches 91.37%; every module ≥85% and
  `api/core/services/engine` ≥90% (enforced by `scripts/coverage_gate.py`).
- `npm run lint`, `typecheck`, `test`, `build`, `format:check`: pass.
- Frontend coverage: statements 90.72%, branches 85.07%, functions 88.42%,
  lines 92.00% (Vitest v8, thresholds 85).
- Playwright: 69 passed on desktop 1440, tablet 1024 and mobile 390; login,
  dashboard, command palette, PWA service worker, axe, LCP/CLS,
  no-horizontal-scroll and stable dark/light visual baselines pass.
- `pip-audit` and full `npm audit`: 0 known vulnerabilities.
- `mkdocs build --strict`, `shellcheck`, clean-wheel install and serve smoke:
  pass.
- First-load JS: 193.4 KiB gzip (budget 300 KiB).
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

## Release status

- [x] Created `v0.1.0` tag and ran Release workflow `43381306485` (success):
      GitHub Release, PyPI `ostium-ctl==0.1.0`, GHCR `0.1.0`/`v0.1.0`/`latest`,
      five core archives, Windows setup and flat `SHA256SUMS` all published.
- [x] Downloaded all Release assets and verified `sha256sum -c SHA256SUMS`;
      real online installer and PyPI install both produced `ostium 0.1.0`.
- [ ] Publish `v0.1.1` if immutable provenance is required for the post-release
      `install-online.sh`/`SHA256SUMS` hotfix (PyPI 0.1.0 sdist and tag source
      still contain the pre-hotfix installer copy).

## External validation still open
- [ ] Run TUN + system proxy acceptance on real Windows 11 and macOS 14, and
      Linux TUN on a privileged host.
- [ ] Run ACME staging and one production issuance on the Hong Kong server.
- [ ] Run a fresh Ubuntu 24.04 systemd installer test and a backup/restore/upgrade drill.
- [ ] Run 72h soak, performance budgets, and the 5-user usability test.
- [ ] Code signing/notarization (optional per PLAN, but SmartScreen/Gatekeeper
      warnings remain).

The full evidence, per-file audit and residual-risk list is in
[`AUDIT_REPORT.md`](AUDIT_REPORT.md).
