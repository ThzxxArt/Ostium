# Ostium

**Ostium** is a dual-role personal VPN and universal proxy console. Install the
same application on a server and on your devices, open the Web UI, and get a
complete private network: Reality, Hysteria2, Trojan and Shadowsocks 2022 on the
server; mixed proxy, system proxy and TUN on the client.

> Status: `v0.1.0` development. See [`PLAN.md`](PLAN.md) for the locked scope.

## Highlights

- **One app, two roles** — server and client share the same Python package, SPA,
  CLI and installer.
- **Aurora Console** — a dark-first, accessible, responsive Web UI with a command
  palette, first-run wizards, live traffic, connection tables and job centre.
- **Real data plane** — a pinned [sing-box](https://sing-box.sagernet.org/)
  `v1.14.4` build with `with_v2ray_api` for per-user accounting.
- **Two services** — an unprivileged control plane (`ostium.service`) and a
  minimal privileged core (`ostium-core.service`).
- **Everything included in v0.1.0** — TUN on Windows/macOS/Linux, system proxy,
  ACME HTTP-01, quotas, four subscription formats, backups, updates, Docker,
  installers, tests and documentation.

## Quick start (development)

```bash
uv sync
uv run ostium init --role server --dev --no-input --password 'change-me-now'
uv run ostium serve
```

PyPI distribution name: `ostium-ctl` (the import/CLI remains `ostium`).

Quality evidence, coverage numbers and remaining external blockers are in
[`AUDIT_REPORT.md`](AUDIT_REPORT.md).

Open <http://127.0.0.1:8443>. In a second terminal start the core service:

```bash
uv run ostium core-run
```

The core uses the pinned sing-box binary at `<data_dir>/core/sing-box`, or
`OSTIUM_ENGINE_PATH`. Official sing-box builds work for all proxy protocols;
per-user V2Ray statistics require the Ostium custom build (`scripts/build-core.sh`).

## Documentation

- [Architecture](docs/architecture.md)
- [Server guide](docs/guides/server.md)
- [Client guide](docs/guides/client.md)
- [Design system](docs/design-system.md)
- [Security model](docs/security/threat-model.md)
- [CLI reference](docs/reference/cli.md)

## License

GPL-3.0-or-later. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). The bundled
sing-box binary is built from unmodified upstream source and remains GPL-3.0.
