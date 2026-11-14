# Ostium v0.1.1

This is a security, correctness and delivery-completeness release for the v0.1
series. It does not add a new proxy protocol.

## Publication

Published on 2026-11-14 from tag `v0.1.1` (commit `a7f5696`). The GitHub
Release, PyPI `ostium-ctl==0.1.1` and GHCR tags `0.1.1`/`v0.1.1`/`latest` are
live. Post-release read-only verification passed for all 23 release assets.
Assets are immutable; fixes go into the next patch release.

## Security and upgrade notes

- The server admin UI now defaults to `127.0.0.1:8443`. Legacy plaintext
  `host = "0.0.0.0"` configurations are migrated to loopback unless
  `allow_insecure_bind = true` is set. Remote administration should use an SSH
  tunnel, or Public UI with a valid TLS certificate and TOTP.
- A non-loopback plaintext admin bind requires the explicit
  `allow_insecure_bind = true` opt-in; `ostium serve` otherwise exits with code 6.
- Server egress now blocks RFC1918, CGNAT, link-local, cloud metadata and SMTP
  port 25.
- Shadowsocks 2022 client passwords use `server_key:user_key`. Existing clients
  must refresh their subscription after upgrading.
- Existing 0.1.0 installations should back up the database, configuration,
  certificates and `master.key` before upgrading. The administrator password is
  unchanged by an upgrade.

## Verification status

This release was built from tag `v0.1.1` with backend tests (585 regular + 10
real sing-box), frontend tests (174), Playwright (69), coverage gates, static
analysis, dependency audits and documentation checks passing.

The following external checks are **not** claimed as verified in this release:
Windows 11 setup/service/TUN/PAC/SmartScreen/uninstall, macOS 14
launchd/utun/system-proxy/DMG/Gatekeeper/notarization, Nginx TLS/WebSocket
reverse proxy, Docker amd64/arm64 runtime, ACME staging/production, real
TUN/Allow LAN/DNS-leak, 72h soak, performance and five-user usability. See the
review ledgers in the repository for the current blocker matrix.

## Signing and assets

- Windows Authenticode and macOS Developer ID/notarization are applied only when
  the release environment has the corresponding secrets. If no certificate is
  configured, the assets are unsigned and are labelled as such; verify the
  published `SHA256SUMS` before installing.
- The AppImage is built by the release workflow. If a platform asset is missing
  or a checksum fails, the release job fails instead of publishing a partial
  release.
- Release assets are immutable. Do not replace files after publication; fixes
  go into the next version.
