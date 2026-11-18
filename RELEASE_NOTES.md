# Ostium v0.1.12

**Status: published on 2026-11-18.** This is a client reliability patch for the
Windows network state left behind by TUN and system-proxy sessions.

## Highlights

- **No more stale TUN blackhole.** Windows clients now stop sing-box with
  `CTRL_BREAK_EVENT` instead of `TerminateProcess`, and the privileged core
  removes stale `Ostium`/`ostium0`/`sing-box` routes and adapters on startup and
  after a TUN session. The "connect once, then TCP to the server times out until
  reboot/uninstall" failure is fixed.
- **No Windows WFP risk from strict routing.** Client TUN configs default to
  `strict_route: false`. sing-box implements strict routing on Windows with WFP
  filters; a hard kill can skip their cleanup and blackhole outbound TCP. Ostium
  has no firewall-level kill switch, so the extra risk is not justified.
- **The system proxy no longer lies.** Windows status checks the live WinINET
  registry instead of the state file. If Clash or another client rewrites
  `ProxyEnable`, `ProxyServer` or `AutoConfigURL`, Ostium reports `stale`,
  re-applies on connect, and the watchdog takes the proxy back while connected.
- **Changing the mixed port moves the proxy.** An enabled system proxy is moved
  to the new `mixed_port` in the same request instead of leaving the browser on
  a closed port.
- **DoH is a real URL.** The client remote resolver now sends `path` and
  `tls.server_name`, not just a bare DoH server IP.

## Upgrade

- `0.1.11 -> 0.1.12` keeps the database, users, credentials, subscription
  tokens, certificates, backups and `master.key`.
- Read `docs/operations/upgrade-0.1.11-to-0.1.12.md`.
- Windows users who already have a stale TUN route should update and restart the
  `OstiumCore` service; the new startup cleanup removes it. A one-time reboot is
  also sufficient. The repair script is in `docs/guides/tun.md`.

## Verified in the implementation workspace

- Backend non-integration suite: 836 passed.
- Targeted proxy/fail-open/settings/config tests: 67 passed with the pinned
  `1.14.4` core.
- Generated client and server configs pass `sing-box check`.
- `scripts/release-preflight.sh --version 0.1.12 --skip-git` passes.

## Not verified

- Windows 11/10 runtime installer, TUN, Wintun/WFP and Authenticode matrix.
- macOS 14 launchd/utun/DMG/notarization.
- Debian/RHEL, Nginx, Docker runtime, ACME, real TUN, 72-hour soak and
  performance.
- The release workflow and platform artifacts are produced from this status
  commit; their run IDs and asset hashes are recorded in
  `docs/release-status.md`.
