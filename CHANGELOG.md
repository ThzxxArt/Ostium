# Changelog

All notable changes to Ostium Server are documented here. This project follows
[Semantic Versioning](https://semver.org/).

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
