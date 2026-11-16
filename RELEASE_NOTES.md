# Ostium v0.1.5

This is a three-fix patch release for login, the Windows client and third-party
Clash subscriptions. It does not add a proxy protocol, change the role model, or
redesign the UI.

## Fixed

- **TOTP login.** The unauthenticated `/api/v1/auth/status` response now exposes
  `login_totp_required`, so the verification-code field is visible on the first
  render instead of appearing only after a failed login. A password-only request
  is treated as a normal challenge and no longer consumes a failed-attempt slot
  or counts toward the account lockout; a supplied-but-wrong TOTP or recovery
  code still does.
- **Windows client startup and CLI.** The installer launches the UI through a
  hidden PowerShell wrapper instead of handing a `.cmd` file to Task Scheduler,
  waits for `http://127.0.0.1:8787/healthz` before reporting success, writes
  startup output to `%ProgramData%\Ostium\logs\ui.log`, and adds
  `%ProgramFiles%\Ostium` to the machine `PATH` so `ostium` works in a new
  terminal. Uninstall removes the PATH entry. The installer also stops the UI
  process before replacing binaries and opens the console after installation.
- **Clash subscriptions.** The generated Clash Meta YAML now enables a fake-IP
  DNS resolver, disables IPv6, and uses `GEOIP,CN,DIRECT,no-resolve`. This keeps
  foreign domains on the proxy path even when the local DNS answer is polluted
  or resolves to a mainland IP; the old bare `GEOIP,CN,DIRECT` rule could send
  Google, YouTube or Hugging Face DIRECT while GitHub happened to work.

## Upgrade notes

- Back up the database, configuration, certificates, rule sets and
  `master.key` before upgrading.
- `0.1.4 -> 0.1.5` keeps the database, users, credentials, subscription tokens,
  certificates, backups and master key. The release workflow runs the upgrade
  path and restores an encrypted backup from the previous release.
- The Windows fix requires the new `Ostium-0.1.5-windows-x64-setup.exe`.
  Reinstalling the old 0.1.4 installer does not add the CLI to `PATH`.
- After upgrading a server, refresh the Clash subscription in the third-party
  client so it downloads the new YAML. A cached 0.1.4 subscription still has the
  old DNS and GEOIP rules.
- System-proxy mode does not capture QUIC. If YouTube or Google still prefer
  direct UDP/443, disable browser QUIC or use TUN mode.
- Windows/macOS binaries are unsigned unless the release owner supplies signing
  certificates. Check `docs/release-status.md` for the current status.

## Verified

- Local backend suite: 712 passed / 10 deselected; 94.32% statements / 90.49%
  branches; coverage gate passed.
- Real sing-box integration with the pinned `1.14.4-ostium.1` core: 10 passed.
- `0.1.4 -> 0.1.5` upgrade and encrypted-backup restore passed; install,
  reinstall and uninstall e2e passed.
- Frontend: 204 tests passed; typecheck, lint, Prettier and production build
  passed.
- Playwright: 73 passed, 2 skipped.
- Generated Clash YAML accepted by Mihomo 1.19.34 with `mihomo -t`.
- Windows installer scripts parsed successfully with PowerShell 7.7; this is a
  syntax check, not a Windows runtime test.
- Exact command output and counts are recorded in `docs/release-status.md`.

## Not verified / accepted blockers

The following were not executed in the development workspace and are not
claimed as verified: Windows 11 runtime, macOS 14 runtime, Debian/RHEL real
machines, Nginx, Docker runtime, real ACME against a public domain, real TUN,
72-hour soak, performance measurements and platform code signing. The Windows
startup fix has not been run on a Windows host in this workspace; it was
validated by script tests and a PowerShell parser only.

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
- `docs/operations/upgrade-0.1.4-to-0.1.5.md`
- `docs/guides/subscription.md`
- `docs/guides/install.md`
