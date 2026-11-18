# Ostium Server

Ostium 0.2.0 is a **single-host, single-administrator private proxy server for Linux**.
It pairs a Django control plane with a supervised [sing-box](https://sing-box.sagernet.org/) data plane.

## What it is

- Four inbounds: VLESS Reality, Hysteria2, Trojan, Shadowsocks 2022.
- Four standard subscriptions: Base64 URI, Clash/Mihomo YAML, sing-box JSON, plain URI.
- Aurora Server Console: live status, traffic charts, quota rings, connections, certificates,
  logs, jobs and audit.
- No custom core API: the worker supervises sing-box directly.
- Secure by default: the console listens on `127.0.0.1:8000`; public exposure requires TLS + TOTP.

## What it is not

- No desktop or mobile client, no TUN, no system proxy.
- No multi-node orchestration, CDN, multi-tenancy or RBAC.
- No migration or compatibility with 0.1.x data, APIs or subscription formats.
- No private subscription format; clients import standards.

## Quick start

```bash
uv sync --extra dev
uv run ostium migrate
uv run ostium init --username admin --password 'Change-This-Password-2026'
uv run ostium web
```

Open <http://127.0.0.1:8000/>. Build the pinned data plane with:

```bash
bash scripts/build-core.sh
cp dist/sing-box .cache/bin/sing-box
uv run ostium worker
```

## Deployment

- `sudo bash install.sh --domain vpn.example.com --with-caddy` (systemd)
- `docker compose -f deploy/docker/compose.yml up -d --build` (Docker)

Documentation: [`docs/index.md`](docs/index.md).

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
