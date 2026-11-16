# Ostium v0.1.8

This is a Windows client patch release. It fixes the UI launcher that killed the
8787 server after uvicorn wrote normal startup INFO to stderr.

## Fixed

- **UI launcher.** The generated `ostium-ui.ps1` used
  `$ErrorActionPreference = "Stop"` around `ostium.exe serve`. PowerShell treated
  uvicorn's normal stderr output as a terminating error and ended the child,
  leaving 8787 without a listener even while `OstiumCore` was running. The
  launcher now uses `Continue`, writes all output to `ui.log`, and checks the
  process exit code.
- **Existing Windows fixes included:** no-argument service dispatcher entry
  (1053), `aiosqlite` bundling, live service logs in interactive installers,
  UI installer fallback, orphan cleanup and the Ostium icon.

## Upgrade notes

- `0.1.7 -> 0.1.8` keeps the database, users, credentials, subscription tokens,
  certificates, backups and master key.
- Windows should run the new `Ostium-0.1.8-windows-x64-setup.exe` over 0.1.7.
- If the browser still shows the cached "cannot read authentication status"
  page, clear site data/Service Worker for `127.0.0.1:8787` or use a private
  window.
- 0.1.8 has no server-side feature changes. A server already on 0.1.7 can stay
  there; upgrading from 0.1.5 or earlier also brings the TOTP and Clash fixes.
- Windows/macOS binaries are unsigned unless the release owner supplies signing
  certificates.

## Verified

- Local backend suite: 713 passed / 10 deselected; coverage gate passed.
- Real sing-box integration with the pinned `1.14.4-ostium.1` core: 10 passed.
- Frontend: 204 tests passed; typecheck, lint, Prettier and production build
  passed.
- Playwright: 73 passed, 2 skipped.
- `0.1.7 -> 0.1.8` upgrade and encrypted-backup restore passed; install,
  reinstall and uninstall e2e passed.
- Windows installer scripts parsed with PowerShell 7.7; the launcher regression
  asserts `ErrorActionPreference = "Continue"`.
- The 0.1.7 UI failure was reproduced from `ui.log`: uvicorn started, PowerShell
  emitted `NativeCommandError`, then the wrapper exited with code 1.

## Not verified / accepted blockers

The following were not executed in the workspace and are not claimed as
verified: Windows 11 runtime of the 0.1.8 installer, macOS 14 runtime,
Debian/RHEL real machines, Nginx, Docker runtime, real ACME against a public
domain, real TUN, 72-hour soak, performance measurements and platform code
signing. The 0.1.8 launcher fix is validated by the reproduced 0.1.7 log and
source tests; the new installer still needs a real Windows run.

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
- `docs/operations/upgrade-0.1.7-to-0.1.8.md`
- `docs/guides/install.md`
- `docs/guides/client.md`
