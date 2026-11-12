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

## Scope notes

- The core API is loopback-only; reports requiring local root or physical access
  are lower priority unless they cross a privilege boundary.
- TUN strict-route is not a kill switch; this is documented behavior.
- Reality/uTLS/Hysteria2 are not claimed to be undetectable.
