# Ostium v0.1.11

**Status: implemented, not published.** No `v0.1.11` tag, GitHub Release, PyPI
artifact or GHCR image exists yet. Publication requires explicit owner approval.

This release is about verifiability and failure containment: prove which build is
running, make installers fail when the wrong process answers, use encrypted DNS
by default, diagnose the actual failing layer, describe online/rate data
honestly, and stop a dead core from blackholing the whole machine.

## Highlights

- **Version provenance.** `ostium version --json`, `/healthz`, `/auth/status`,
  `/system/info`, `/system/provenance` and the core API report comparable
  version/commit/process facts. A stale process on the UI port is visible as a
  PID/path mismatch instead of silently serving the old release.
- **Installer contract.** Windows, Linux and macOS installers assert the expected
  version and refuse to kill an unknown process on the UI port. A stale
  `python.exe -m ostium serve` no longer makes an upgrade report success.
- **DNS v2.** Server DNS defaults to DoH first, UDP only as an explicit fallback.
  The dead `local2` server is gone, `CONFIG_POLICY_VERSION` is 3, and
  `last-good.meta.json` records the mode, servers and probe time.
- **Diagnostics v2.** Doctor covers version consistency, port ownership, core
  readiness, configuration drift, DoH comparison, direct/proxy egress, system
  proxy, TUN and disk. `/system/selftest` reports DNS/TCP/TLS/HTTP stage and
  latency.
- **Honest status.** Online means traffic seen within a configurable window
  (default 60 s), not a TCP connection count. Rates decay and reset during
  outages; users/subscriptions pages poll while visible.
- **Fail-open.** If the client core is unavailable for 45 s, the system proxy is
  disabled and direct internet is restored with a critical alert. It is
  re-enabled after the core recovers, but never after an explicit Disconnect.
  This is not a kill switch.
- **No database migration.**

## Upgrade

- `0.1.10 -> 0.1.11` keeps the database, users, credentials, subscription tokens,
  certificates, backups and `master.key`.
- Read `docs/operations/upgrade-0.1.10-to-0.1.11.md`.
- Rollback to 0.1.10 intentionally leaves the core down until the older control
  plane regenerates a policy-2 configuration.

## Verified in the implementation workspace

- Backend: 825 passed, 94.28% statements / 90.32% branches, coverage gate passed.
- Real `1.14.4-ostium.1` core integration: 10 passed.
- Frontend: 219 unit tests, 73 Playwright tests passed; coverage 90.78/85.04.
- `0.1.10 -> 0.1.11` and `0.1.9 -> 0.1.11` upgrades plus encrypted-backup
  restore passed.
- Wheel/sdist exact `0.1.11`; wheel CLI and bundled Web `build.json` match.
- Release preflight, shellcheck, `bash -n` and `mkdocs --strict` passed.

## Not published / not verified

- Windows 11, macOS 14, Debian/RHEL, Nginx, Docker, ACME, real TUN and 72-hour
  soak tests still require external hardware, domains or accounts.
- Windows Authenticode and Apple Developer ID certificates are not configured.
- Available validation evidence is recorded in `docs/release-status.md` and the
  final implementation report; unexecuted items are not claimed as verified.
