# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.2.x | yes |
| 0.1.x | no |

## Reporting a vulnerability

Do not open a public issue. Email the maintainers with:

- affected version and commit;
- reproduction steps;
- impact and any suggested fix;
- whether you want public credit.

We aim to acknowledge within 72 hours and provide a remediation plan within 7 days.

## Deployment expectations

Ostium is a private proxy server. Operators are responsible for:

- keeping the host, Python environment and sing-box patched;
- using TLS for the management plane;
- enabling TOTP before public exposure;
- restricting firewall ports;
- protecting `OSTIUM_SECRET_KEY`, `OSTIUM_FIELD_KEY` and backups;
- reviewing audit events and alerts.

## Scope

In scope: authentication bypass, subscription token leakage, command injection,
path traversal, SSRF in webhooks, unsafe deserialization, privilege escalation,
configuration injection into sing-box.

Out of scope: DDoS, physical access, compromised host, third-party clients,
misconfiguration explicitly warned about in the docs.
