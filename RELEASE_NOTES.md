# Ostium v0.1.6

This is a Windows client patch release. It fixes the frozen bundle and service
startup failures found after 0.1.5; no proxy protocol or UI redesign is included.

## Fixed

- **Missing `aiosqlite`.** SQLAlchemy imports the async SQLite DBAPI dynamically.
  Both PyInstaller bundles now collect `aiosqlite`; the UI and core service no
  longer exit during FastAPI lifespan startup with `ModuleNotFoundError`.
- **Windows service 1053 timeout.** The service entry point now reaches the SCM
  dispatcher before importing FastAPI, uvicorn and the core app. On machines
  where the frozen bundle import took longer than the 30-second SCM window, the
  service previously failed with error 1053. Heavy imports now run inside
  `SvcDoRun`, after the service is reported running.
- **Installer no longer blocks the UI.** If `OstiumCore` cannot start, the UI
  task is still registered and the 8787 health check still runs. The service
  failure and `sc.exe qc` output are written to
  `%ProgramData%\Ostium\logs\install.log`.
- **Service diagnostics.** Startup exceptions and uvicorn output go to
  `%ProgramData%\OstiumCore\logs\service.log`; import failures go to
  `service-bootstrap.log`.
- **Orphan cleanup.** Reinstalling stops leftover `ostium-service` and
  `sing-box` processes that could hold port 8788 and make the replacement
  service exit immediately.
- **Installer icon.** The setup executable and both application executables now
  embed the Ostium icon.

The 0.1.5 TOTP and Clash subscription fixes remain included when upgrading from
0.1.4 or earlier.

## Upgrade notes

- Back up the database, configuration, certificates, rule sets and
  `master.key` before upgrading a server.
- `0.1.5 -> 0.1.6` keeps the database, users, credentials, subscription tokens,
  certificates, backups and master key. The release workflow runs the upgrade
  path and restores an encrypted backup from the previous release.
- Windows must run the new `Ostium-0.1.6-windows-x64-setup.exe`; replacing only
  `ostium.exe` does not fix the missing bundle dependency or service imports.
- After a server upgrade, third-party Clash clients should refresh their
  subscription if they still hold a 0.1.4 or older profile.
- Windows/macOS binaries are unsigned unless the release owner supplies signing
  certificates. Check `docs/release-status.md` for the current status.

## Verified

- Local backend suite: 713 passed / 10 deselected; coverage gate passed.
- Real sing-box integration with the pinned `1.14.4-ostium.1` core: 10 passed.
- Frontend: 204 tests passed; typecheck, lint, Prettier and production build
  passed.
- Playwright: 73 passed, 2 skipped.
- `0.1.5 -> 0.1.6` upgrade and encrypted-backup restore passed; install,
  reinstall and uninstall e2e passed.
- Windows installer scripts parsed with PowerShell 7.7; generated service
  wrapper and UI wrapper templates parsed too.
- The 0.1.5 startup failure was reproduced on Windows as
  `ModuleNotFoundError: No module named 'aiosqlite'`. The 0.1.6 bundle now
  collects the package.
- Exact command output and counts are recorded in `docs/release-status.md`.

## Not verified / accepted blockers

The following were not executed in the workspace and are not claimed as
verified: Windows 11 runtime of the 0.1.6 installer, macOS 14 runtime,
Debian/RHEL real machines, Nginx, Docker runtime, real ACME against a public
domain, real TUN, 72-hour soak, performance measurements and platform code
signing. The 0.1.6 Windows service startup path is validated by source tests,
PowerShell parsing and the reproduced 0.1.5 root cause; the new installer still
needs a real Windows run.

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
- `docs/operations/upgrade-0.1.5-to-0.1.6.md`
- `docs/guides/install.md`
- `docs/guides/client.md`
