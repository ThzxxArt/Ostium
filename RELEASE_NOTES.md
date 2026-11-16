# Ostium v0.1.10

This is a server-side DNS patch. Clients do not need to be reinstalled.

## Fixed

- **Polluted server DNS.** The server used `223.5.5.5` for sing-box outbound
  resolution. On the deployed host it returned Facebook/Twitter addresses for
  Google and Hugging Face, so TCP connected but TLS failed. GitHub happened to
  resolve correctly. Server configs now use `8.8.8.8` and `1.1.1.1` with the
  existing `ipv4_only` strategy.
- **Included fixes:** server `ipv4_only` from 0.1.9; Windows UI launcher,
  service dispatcher, `aiosqlite`, live installer logs and icons from 0.1.6
  through 0.1.8.

## Upgrade notes

- `0.1.9 -> 0.1.10` keeps the database, users, credentials, subscription
  tokens, certificates, backups and master key.
- Upgrade the server, then disconnect/reconnect the client or wait for the
  watchdog to apply the new configuration. No Windows installer update is
  required for this release.
- If the client page still reports 0.1.7, check `ostium version`,
  `Get-Process ostium` and the process path; an old UI process or a different
  installation can keep serving the old version.
- Online users are a 60-second traffic window, not a TCP connection count.
- Windows/macOS binaries remain unsigned unless the release owner supplies
  signing certificates.

## Verified

- Local backend suite: 713 passed / 10 deselected; coverage gate passed.
- Real sing-box integration with the pinned `1.14.4-ostium.1` core: 10 passed.
- Frontend: 204 tests passed; typecheck, lint, Prettier and production build
  passed.
- Playwright: 73 passed, 2 skipped.
- `0.1.9 -> 0.1.10` upgrade and encrypted-backup restore passed; install,
  reinstall and uninstall e2e passed.
- Server evidence: `223.5.5.5` returned `104.244.42.197` for Google and
  `157.240.3.8` for Hugging Face; system DNS returned correct A records. The
  generated config with `8.8.8.8`/`1.1.1.1` passes `sing-box check`.

## Not verified / accepted blockers

The following were not executed in the workspace and are not claimed as
verified: Windows 11 runtime, macOS 14 runtime, Debian/RHEL real machines,
Nginx, Docker runtime, real ACME against a public domain, real TUN, 72-hour
soak, performance measurements and platform code signing.

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
- `docs/operations/upgrade-0.1.9-to-0.1.10.md`
- `docs/guides/install.md`
- `docs/guides/client.md`
