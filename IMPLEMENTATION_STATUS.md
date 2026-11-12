# Ostium v0.1.0 implementation status

Updated: 2026-11-12

Legend: `[x]` implemented and exercised locally, `[~]` implemented but needs
platform/external validation, `[ ]` not done yet.

## Delivered in this workspace

### Backend and data plane

- [x] Python 3.13 package `ostium-art`, import/CLI `ostium`, GPL-3.0-or-later.
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
- [x] Real sing-box 1.14.4 config checks and a local Reality loopback traffic
      test (curl → client mixed → server Reality → example.com).
- [x] Users, credentials, quotas, expiry, subscription tokens, token rotation.
- [~] V2Ray per-user stats client/collector, epoch reset, daily flush, quota
      enforcement (logic tested with a fake gRPC source; custom core build not
      compiled in this environment).
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
- [~] Browser notifications and service-worker update prompt are not wired into
      the UI yet (API/PWA foundation exists).
- [~] Visual regression baselines are configured but not generated; axe smoke
      is present in Playwright spec.

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

- `ruff check` / `ruff format --check`: pass.
- `mypy src/ostium` strict: pass (generated protobuf and platform-only proxy
  modules excluded/ignored).
- `pytest`: 37 passed locally, including real sing-box config checks and core
  apply/stop. Integration tests skip if no core binary.
- `npm run lint`, `typecheck`, `test`, `build`, `format:check`: pass locally.
- Coverage: approximately 45% overall; below the PLAN gate (core/services 85%,
  overall 70%). Additional tests are required before release.
- Real ACME, Windows/macOS TUN, Windows service, macOS launchd, Windows/macOS
  system proxy, 72h soak, usability tests and installer-on-fresh-VM are not
  run in this environment.

## Design deviations / ADRs

- TypeScript 7.0.2 is not compatible with `vue-tsc` (it resolves the removed
  `typescript/lib/tsc` path). v0.1.0 uses TypeScript 6.0.3 and vue-tsc 3.3.14.
  See `docs/adr/0001-typescript-6.md`.
- The official sing-box 1.14.4 release lacks `with_v2ray_api`; per-user stats
  require `scripts/build-core.sh`. All other protocols/TUN are tested with the
  official binary.
- Default smart routing uses an offline curated domain-suffix list, not remote
  GeoIP/GeoSite downloads, so first start does not depend on GitHub reachability.
  Users can add remote rule sets explicitly.
- The UI uses `create_all` + an Alembic stamp for the initial schema and ships
  the initial migration; future schema changes use Alembic.

## Release blockers still open

- [ ] Raise coverage to the PLAN gate and add ACME/certificate/profile/auth/jobs
      tests.
- [ ] Compile the custom `with_v2ray_api` core and verify per-user stats against
      a real gRPC endpoint.
- [ ] Run TUN + system proxy acceptance on real Windows 11 and macOS 14.
- [ ] Run ACME staging and one production issuance on the Hong Kong server.
- [ ] Run a fresh Ubuntu 24.04 installer test and a backup/restore/upgrade drill.
- [ ] Generate and commit visual baselines; fix any serious axe findings.
- [ ] Add browser notification permission flow and PWA update prompt.
- [ ] Run 72h soak, performance budgets, and the 5-user usability test.
- [ ] Code signing/notarization (optional per PLAN, but SmartScreen/Gatekeeper
      warnings remain).
- [ ] Replace `backup.title` fallback text and other untranslated microcopy found
      during the language pass.
