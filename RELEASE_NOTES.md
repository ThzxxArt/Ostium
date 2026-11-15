# Ostium v0.1.4

This is a one-fix patch release for the Subscriptions page. It does not add a
proxy protocol, change the role model, or redesign the UI.

## Fixed

- Long subscription URLs no longer overflow the format cards. The two-column
  grid now uses shrinkable tracks, the URL is a block element so ellipsis
  applies, and card headers truncate long names. A Playwright layout regression
  covers a 160-character token on desktop, tablet and mobile.

## Upgrade notes

- Back up the database, configuration, certificates, rule sets and
  `master.key` before upgrading.
- `0.1.3 -> 0.1.4` keeps the database, users, credentials, subscription tokens,
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
- `docs/operations/upgrade-0.1.3-to-0.1.4.md`
- `docs/operations/backup.md`
- `docs/guides/nginx.md`
