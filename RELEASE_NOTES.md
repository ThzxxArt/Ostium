# Ostium v0.1.7

This is a Windows client patch release. It fixes the frozen service dispatcher
entry point that caused SCM error 1053 and adds real-time service logs to the
interactive installer.

## Fixed

- **Windows service 1053.** `sc qc OstiumCore` starts the frozen executable with
  no arguments. `win32serviceutil.HandleCommandLine` treats an empty argument
  list as a usage request and exits, so SCM never receives a dispatcher and
  reports error 1053. The no-argument path now calls
  `servicemanager.Initialize`, `PrepareToHostSingle` and
  `StartServiceCtrlDispatcher` itself. `debug`, `install` and `remove` still use
  `HandleCommandLine`.
- **Installer real-time logs.** Interactive installs show the final service step
  in a visible PowerShell console, mirroring service registration,
  `Start-Service`, the 8787 health check and failure details. Silent installs
  remain hidden and still write `%ProgramData%\Ostium\logs\install.log`.

The 0.1.6 `aiosqlite` bundle fix, UI/service diagnostics, orphan cleanup and
application icon are included.

## Upgrade notes

- Back up the database, configuration, certificates, rule sets and
  `master.key` before upgrading a server.
- `0.1.6 -> 0.1.7` keeps the database, users, credentials, subscription tokens,
  certificates, backups and master key.
- Windows should run the new `Ostium-0.1.7-windows-x64-setup.exe` over 0.1.6;
  replacing only `ostium.exe` does not update the service or installer.
- 0.1.7 has no server-side feature changes. A server already on 0.1.6 can stay
  there; upgrading from 0.1.5 or earlier also brings the TOTP and Clash fixes.
- Windows/macOS binaries are unsigned unless the release owner supplies signing
  certificates.

## Verified

- Local backend suite: 713 passed / 10 deselected; coverage gate passed.
- Real sing-box integration with the pinned `1.14.4-ostium.1` core: 10 passed.
- Frontend: 204 tests passed; typecheck, lint, Prettier and production build
  passed.
- Playwright: 73 passed, 2 skipped.
- `0.1.6 -> 0.1.7` upgrade and encrypted-backup restore passed; install,
  reinstall and uninstall e2e passed.
- Windows installer scripts parsed with PowerShell 7.7; Inno Setup `[Run]`
  interactive/silent branches and the generated wrappers are covered by source
  tests.
- The 0.1.5 service failure was reproduced from `sc qc`: the service image had
  no arguments, and `debug` worked because it supplied one.

## Not verified / accepted blockers

The following were not executed in the workspace and are not claimed as
verified: Windows 11 runtime of the 0.1.7 installer, macOS 14 runtime,
Debian/RHEL real machines, Nginx, Docker runtime, real ACME against a public
domain, real TUN, 72-hour soak, performance measurements and platform code
signing. The 0.1.7 Windows service path is validated by the reproduced SCM
command line and source tests; the new installer still needs a real Windows run.

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
- `docs/operations/upgrade-0.1.6-to-0.1.7.md`
- `docs/guides/install.md`
- `docs/guides/client.md`
