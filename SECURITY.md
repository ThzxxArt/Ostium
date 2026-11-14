# Security policy

Ostium is a personal VPN/proxy control plane. Security reports are taken
seriously, especially authentication bypass, core API escapes, CSRF/DNS
rebinding, subscription token leakage and supply-chain issues.

## Reporting

Please use GitHub private security advisories:
<https://github.com/ThzxxArt/Ostium/security/advisories/new>

Do not open a public issue for an exploitable problem. Include:

- Ostium version and platform
- Whether the control plane, core or a protocol is affected
- Reproduction steps and impact
- Any suggested fix

We aim to acknowledge within 72 hours and to publish a coordinated advisory
after a fix is available.

## Supported versions

Only the latest v0.1.x release receives security fixes during the v0.1 series.
v0.1.1 fixes the default admin bind issue documented in
[`docs/security/advisory-2026-11-default-bind.md`](docs/security/advisory-2026-11-default-bind.md).
**v0.1.1 is not published yet.** Until it is available, v0.1.0 operators must
apply the mitigation in `V0.1.1_PLAN.md` §2: bind the UI to `127.0.0.1`, do not
expose 8443, and enable TOTP plus a valid certificate before public access.

## Scope notes

- Server admin UI defaults to `127.0.0.1`; non-loopback plaintext requires an
  explicit `allow_insecure_bind` opt-in. Reports that rely on a deliberately
  public plaintext bind are accepted but may be lower priority.
- The core API is loopback-only; reports requiring local root or physical access
  are lower priority unless they cross a privilege boundary.
- TUN strict-route is not a kill switch; this is documented behavior.
- Reality/uTLS/Hysteria2 are not claimed to be undetectable.
