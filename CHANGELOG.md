# Changelog

All notable changes to Ostium Server are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## 0.2.8 — 2026-11-19

### Fixed

- Full subscription and single-node URLs no longer get clipped by
  `text-overflow: ellipsis` or the subscription panel's `overflow: hidden`.
  They wrap at any character, remain fully visible, and can be selected with
  one click.
- Each full URL now has an inline **复制** button. Clipboard writes fall back to
  the legacy copy path when the async Clipboard API is denied, instead of
  failing silently.
- Grid and flex children can shrink below their content width, preventing long
  links from pushing panels past the viewport.

## 0.2.7 — 2026-11-19

### Fixed

- Console pages no longer link to Django Admin. The following are now native
  Aurora pages or actions:
  - **新增用户** (`/users/new/`) with quota, quota cycle, expiry, note and
    enabled state;
  - user editing remains on the console user detail page;
  - certificate management stays on `/certificates/`;
  - inbound editing stays on `/inbounds/`;
  - audit filtering stays on `/audit/`.
- The Django Admin navigation and user menu entries were removed from the
  console shell and command palette.
- Django Admin is now labelled **Ostium 应急管理** and clearly states that
  normal operations belong in the Aurora console.
- Console eyebrow labels and remaining visible form headings are Chinese.
- New users created from the console now persist `expires_at` correctly.

## 0.2.6 — 2026-11-19

### Fixed

- The installer now imports already-existing certbot certificates during
  install and upgrade, instead of waiting for the next renewal hook.
- The certificates page has a **同步 certbot** action for staged certificates.
- Inbound TLS certificate selectors link to certificate management/import and
  immediately list synced certificates.
- Certificate import supports three input modes: file upload, selecting a
  staged server certificate directory, and pasting PEM. Domain is optional and
  auto-detected from the certificate.

## 0.2.5 — 2026-11-19

### Fixed

- The console settings page now resolves bound form fields instead of rendering
  `<django.forms.fields.CharField object ...>`, uses Chinese labels/help text,
  and no longer has a sticky save bar overlaying fields.
- Certificate import moved from a broken Django admin page to a first-class
  Aurora console page at `/certificates/import/`, with Chinese labels and the
  same layout as the rest of the console.
- The system page now explains configuration revisions in plain language
  (`配置应用状态`, `已同步/等待应用`, internal revision number) instead of two raw
  numbers labelled “expected/applied version”.
- Swagger UI is served from `drf-spectacular-sidecar` with a CSP nonce, so
  `/api/docs` renders instead of a blank page.
- Django Admin app groups use Chinese names; user quota fields display
  human-readable values such as `100.0 GiB` instead of raw bytes; protocol
  validation messages are Chinese.
- Added full-page screenshots and automated checks for settings, system,
  certificates, users, subscriptions, inbounds, connections, logs, jobs, audit,
  user detail, admin index/changelists, certificate import and API docs.

## 0.2.4 — 2026-11-19

### Fixed

- Production `SECURE_REDIRECT_EXEMPT` patterns now omit the leading slash,
  matching how Django strips the path before matching. `/healthz`, `/readyz`
  and `/metrics` no longer return 301 on the loopback listener.

## 0.2.3 — 2026-11-19

### Fixed

- `ostium web` now resolves `gunicorn` next to the running venv Python before
  falling back to `PATH`. This fixes systemd startup
  (`CommandError: gunicorn is not installed in this environment`) when the
  console script is invoked by absolute path.

## 0.2.2 — 2026-11-19

### Fixed

- The installer now uses immutable GitHub Release assets by default: the wheel,
  sdist (for systemd/Caddy/certbot files), prebuilt sing-box and `SHA256SUMS`.
  Source checkout/build is only used with `--from-source`.
- Removed the Chart.js `sourceMappingURL` comment from the vendored bundle and
  moved the Tailwind source stylesheet out of `static/`. Production
  `collectstatic` with `CompressedManifestStaticFilesStorage` now succeeds.
- Added a CI regression test that runs `collectstatic` with the real manifest
  storage backend.

## 0.2.1 — 2026-11-18

### Fixed

- The installer now forces uv to use a managed Python under `/opt/ostium/python`
  and keeps uv executable links out of `/root/.local/bin`. This fixes
  `runuser: failed to execute /opt/ostium/venv/bin/python: Permission denied`
  on hosts where root's `PATH` already contained an unmanaged Python 3.14.
- Existing venvs that resolve outside `/opt/ostium/python` are detected and
  rebuilt automatically during install/upgrade.
- venv and managed Python permissions are normalized so the `ostium` service
  user can execute them.

No database schema changes; 0.2.0 installations can upgrade in place.

## 0.2.0 — 2026-11-18

### Added

- Django 6.1 control plane with Unfold admin and the Aurora Server Console.
- VLESS Reality, Hysteria2, Trojan and Shadowsocks 2022 inbounds.
- Standard subscriptions: Base64 URI, Clash/Mihomo YAML, sing-box JSON, plain URI.
- Worker that supervises a pinned sing-box binary, validates configuration with
  `sing-box check`, applies atomically and rolls back on failure.
- V2Ray gRPC traffic accounting, quota enforcement, monthly rollover, daily history.
- TOTP, recovery codes, login lockout, API keys with scopes, audit trail.
- Encrypted backups, certbot synchronisation, doctor and redacted diagnostics.
- systemd units, Docker Compose, installer, release scripts and CI.
- Aurora design system with dark/light themes, responsive layouts and WCAG 2.2 AA targets.

### Changed

- The project is server-only. There is no client, SPA, TUN or system proxy.
- TLS is handled by certbot and Caddy; the built-in ACME implementation is gone.
- The API is a new `/api/v1` contract with RFC 9457 errors.

### Removed

- FastAPI, SQLAlchemy, Alembic, Typer, the custom core API and the Vue SPA.
- Windows, macOS, DEB, AppImage, DMG and PyInstaller packaging.
- All 0.1.x data migration, compatibility and upgrade paths.

> 0.1.x installations are not supported by this release. Install fresh and
> recreate users, certificates and subscriptions.
