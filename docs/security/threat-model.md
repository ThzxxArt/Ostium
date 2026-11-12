# Security model

## Trust boundaries

| Boundary | Trusted | Untrusted |
|---|---|---|
| Internet → 443 | authenticated proxy users | scanners, probes, unauthenticated traffic |
| Internet → admin UI | admin with TLS+TOTP | public attackers |
| UI user → core API | UI user with token | other local users |
| Core → sing-box | fixed binary, validated JSON | arbitrary commands/paths |
| Browser → local UI | local user + token | malicious web pages/DNS rebinding |
| Supply chain | pinned versions + checksums | mirror tampering |

## Controls

- Single admin, Argon2id, optional TOTP (mandatory for public UI), recovery
  codes, session idle/absolute expiry, login throttling.
- CSRF double-submit cookie, Origin checks, TrustedHost/DNS-rebinding
  protection, CSP, HSTS when HTTPS, `frame-ancestors 'none'`.
- Core API only on loopback with constant-time bearer comparison, 2 MiB body
  limit, strict JSON, role whitelist, port/path checks and `sing-box check`.
- AES-256-GCM field encryption with AAD; master key 0600; backup encryption with
  scrypt + AES-256-GCM.
- Logs redact UUIDs, tokens, passwords, private keys, proxy URIs and
  Authorization headers.
- Subscription tokens are hashed for lookup and encrypted for recovery; public
  responses set `no-referrer` and `no-store`.
- Server egress blocks cloud metadata, loopback, link-local, private ranges and
  SMTP 25 by default.

## Residual risks

- A compromised or seized server exposes metadata and online users.
- Reality/uTLS/Hysteria2 can be fingerprinted or blocked; there is no permanent
  stealth guarantee.
- TUN `strict_route` is not a standalone kill switch.
- Quotas pause when the control plane is down.
- Core reloads cause brief disconnects and sampling error.
- Local malware running as the same user can control the VPN (but not obtain a
  root shell).
- Unsigned Windows/macOS builds lower MITM resistance; verify checksums or build
  yourself.
- Upstream sing-box/dependency 0-days require prompt updates.
- Legal and cloud AUP compliance is the operator's responsibility.

## Reporting

Do not open a public issue for a vulnerability. Use GitHub private security
advisories or the contact in `SECURITY.md`. Include version, platform, steps and
whether the core or control plane is affected.
