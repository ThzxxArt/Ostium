# Ostium v0.1.9

This is a server-side DNS/egress patch for IPv4-only VPS hosts. Clients do not
need to be reinstalled.

## Fixed

- **IPv4-only server DNS.** Server-generated sing-box configurations now set
  `dns.strategy: ipv4_only` and route outbound domain resolution through the
  internal `local` DNS server. Previously an IPv4-only VPS could resolve Google
  or Hugging Face to AAAA, time out on the direct outbound, and make the client
  fail the TLS handshake after a successful HTTP CONNECT. IPv4-only GitHub
  worked, which made the failure look domain-specific.
- **Included Windows fixes:** the 0.1.8 UI launcher no longer treats uvicorn's
  stderr as a terminating error; the 0.1.7 service dispatcher entry, 0.1.6
  `aiosqlite` bundle, live installer logs, diagnostics and icon remain included.

## Upgrade notes

- `0.1.8 -> 0.1.9` keeps the database, users, credentials, subscription tokens,
  certificates, backups and master key.
- Upgrade the server, then disconnect/reconnect the client or wait for the
  watchdog to apply the new configuration. No Windows installer update is
  required for this release.
- The server must have working IPv4 egress. IPv6 is intentionally not used by
  the generated server DNS; `ipv4_only` avoids IPv4-only VPS failures.
- Online users are counted by a 60-second traffic window, not by TCP connection
  state. A disconnected client clears after the window; closing only the browser
  does not disconnect the tunnel.
- Windows/macOS binaries remain unsigned unless the release owner supplies
  signing certificates.

## Verified

- Local backend suite: 713 passed / 10 deselected; coverage gate passed.
- Real sing-box integration with the pinned `1.14.4-ostium.1` core: 10 passed.
- Frontend: 204 tests passed; typecheck, lint, Prettier and production build
  passed.
- Playwright: 73 passed, 2 skipped.
- `0.1.8 -> 0.1.9` upgrade and encrypted-backup restore passed; install,
  reinstall and uninstall e2e passed.
- Generated server configuration with `dns.strategy: ipv4_only` and
  `route.default_domain_resolver` passes `sing-box check`.
- The reported failure was reproduced from the server: IPv4 `curl` returned 200
  for Google/Hugging Face, IPv6 failed, while GitHub was IPv4-only and worked.

## Not verified / accepted blockers

The following were not executed in the workspace and are not claimed as
verified: Windows 11 runtime, macOS 14 runtime, Debian/RHEL real machines,
Nginx, Docker runtime, real ACME against a public domain, real TUN, 72-hour
soak, performance measurements and platform code signing. The IPv4-only fix is
validated by generated-config checks and the server/client evidence above.

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
- `docs/operations/upgrade-0.1.8-to-0.1.9.md`
- `docs/guides/install.md`
- `docs/guides/client.md`
