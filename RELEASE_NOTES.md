# Ostium v0.1.3

This is a patch release for deployment reliability. It does not add a proxy
protocol, change the role model, or redesign the UI.

## Fixed

- The collapsed sidebar no longer overlaps the expand button with the brand
  mark; both stack inside the 76 px rail.
- The Logs page level filter keeps a stable 130 px width instead of collapsing
  to one visible letter.
- The dashboard no longer returns `500 internal server error` on VPS or
  container network stacks where `psutil.net_if_addrs()` raises
  `EAFNOSUPPORT`. LAN address hints are optional and no longer take down
  `/api/v1/system/info`.
- A fresh server install no longer reports "core is not running" when the core
  is healthy. The installer readiness check uses the unauthenticated
  `/v1/health` endpoint instead of the bearer-token-protected `/v1/status`.
- Release e2e scripts carry the executable bit and are invoked through `bash`;
  the sudo install step preserves `PATH` so `uv` remains available.

## Upgrade notes

- Back up the database, configuration, certificates, rule sets and
  `master.key` before upgrading.
- `0.1.2 -> 0.1.3` keeps the database, users, credentials, subscription tokens,
  certificates, backups and master key. The upgrade path is covered by the
  release workflow.
- A backup without `master.key` is rejected when the database contains
  encrypted fields. Restore the original key; do not generate a new one.
- Windows/macOS binaries are unsigned unless the release owner supplies signing
  certificates. Check `docs/release-status.md` for the current status.

## Verified

- Local backend, frontend, real-core integration, backup portability, upgrade
  and release-ordering tests.
- Exact command output and counts are recorded in `docs/release-status.md`.

## Not verified / accepted blockers

The following were not executed in the development workspace and are not
claimed as verified: Windows 11 runtime, macOS 14 runtime, Debian/RHEL real
machines, Nginx, Docker runtime, real ACME against a public domain, real TUN,
72-hour soak, performance measurements and platform code signing. See
`docs/release-status.md` for the maintained list.

## Signing and artifacts

Artifacts are published with SHA-256 checksums, a core manifest and GitHub build
provenance attestations. Platform signing is listed separately; do not describe
an unsigned asset as signed.

## Rollback

Keep the previous virtualenv and a database snapshot. Restore the snapshot and
the previous package if the upgrade fails. The backup restore path keeps a
staged backup for retry and restores the previous database on error.

## Documentation

- `docs/release-status.md`
- `docs/operations/upgrade-0.1.2-to-0.1.3.md`
- `docs/operations/backup.md`
- `docs/guides/nginx.md`
