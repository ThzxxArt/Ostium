# Ostium Server 0.2.1 — Release Notes

Ostium 0.2.1 is a patch release for the server-only 0.2.x line. It fixes the
online installer on hosts where root already had a Python 3.14 executable in
`/root/.local/bin`.

## Fixed

- The installer forces `UV_PYTHON_PREFERENCE=only-managed`, installs Python
  under `/opt/ostium/python`, and writes uv executable links to
  `/opt/ostium/bin` instead of `/root/.local/bin`.
- Existing venvs that resolve outside `/opt/ostium/python` are detected and
  rebuilt automatically.
- The installer verifies the venv interpreter with `runuser -u ostium` before
  continuing, and normalizes directory permissions.

This fixes:

```text
runuser: failed to execute /opt/ostium/venv/bin/python: Permission denied
```

No database schema changes. 0.2.0 installations can upgrade in place.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

```bash
pip install ostium-ctl==0.2.1
```

```bash
docker pull ghcr.io/thzxxart/ostium-server:0.2.1
```

## Published channels

- PyPI: https://pypi.org/project/ostium-ctl/0.2.1/
- GHCR: `ghcr.io/thzxxart/ostium-server:0.2.1` and `:latest`
- GitHub Release: `v0.2.1`

## 0.2.0 highlights

- One host, one admin: Django 6.1 + SQLite/PostgreSQL.
- VLESS Reality, Hysteria2, Trojan, Shadowsocks 2022.
- Base64, Clash/Mihomo, sing-box and plain URI subscriptions.
- Pinned sing-box with `sing-box check`, atomic apply and rollback.
- Aurora Console, TOTP, scoped API keys, audit, encrypted backups, doctor,
  diagnostics, Prometheus and certbot sync.
- systemd, Docker Compose, one-line installer and pinned container image.

## Breaking changes from 0.1.x

- 0.1.x databases, configuration, certificates, tokens, APIs and subscription
  formats are not read or migrated.
- The client, TUN, system proxy, SPA and custom core API are removed.
- Python 3.14 and Django 6.1 are required.
