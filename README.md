# Ostium Server

Ostium 0.2.0 is a single-host, single-administrator private proxy server for Linux.
It runs a Django control plane and supervises a pinned [sing-box](https://sing-box.sagernet.org/)
data plane. There is no desktop or mobile client: any standards-compatible client imports
the generated subscription.

- Protocols: VLESS + Reality, Hysteria2, Trojan, Shadowsocks 2022
- Subscriptions: Base64 URI, Clash/Mihomo YAML, sing-box JSON, plain URI
- Admin: Django Admin (Unfold) plus the Aurora Server Console
- Deployment: systemd or Docker Compose, SQLite by default, PostgreSQL optional
- TLS: certbot for certificates, Caddy for the management plane

Full documentation lives in [`docs/`](docs/index.md).

## Quick start (development)

```bash
uv sync --extra dev
uv run ostium migrate
uv run ostium init --username admin --password 'change-me-now'
uv run ostium web
```

Open <http://127.0.0.1:8000/>.

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
