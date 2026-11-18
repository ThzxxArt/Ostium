# Ostium Server 0.2.0 — Release Notes

Ostium 0.2.0 is a ground-up server-only rewrite.

## Highlights

- **One host, one admin.** Django + SQLite/PostgreSQL, no external control plane.
- **Four protocols.** VLESS Reality, Hysteria2, Trojan, Shadowsocks 2022.
- **Standard subscriptions.** Import into v2rayN, Clash Verge Rev, sing-box and others.
- **Real data plane.** Pinned sing-box with `with_v2ray_api`; configuration validated
  by the binary before every apply, with rollback.
- **Aurora Console.** Dark-first, responsive, keyboard accessible, charts and quota rings.
- **Operational maturity.** TOTP, lockout, scoped API keys, audit, encrypted backups,
  doctor, diagnostics, Prometheus metrics, certbot sync.

## Breaking changes

- 0.1.x databases, configuration, certificates, tokens, APIs and subscription formats
  are **not** read or migrated.
- The client, TUN, system proxy, SPA and custom core API are removed.
- Python 3.14 and Django 6.1 are required.

## Install

```bash
sudo bash install.sh --domain vpn.example.com --with-caddy
```

or

```bash
docker compose -f deploy/docker/compose.yml up -d --build
```

Read `docs/installation.md` and the security checklist before exposing the console.
