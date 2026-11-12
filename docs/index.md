# Ostium

Ostium is a dual-role personal VPN and universal proxy console. The same Python
package runs on a server and on your devices, with one Web UI, one CLI and one
installer. The data plane is a pinned sing-box build; the control plane is
FastAPI + Vue 3.

## Start here

- [Architecture](architecture.md) — processes, ports, trust boundaries.
- [Server guide](guides/server.md) — install on Ubuntu/Debian/Hong Kong VPS.
- [Client guide](guides/client.md) — install on Windows, macOS or Linux.
- [TUN guide](guides/tun.md) — permissions, routing and known limits.
- [ACME guide](guides/acme.md) — HTTP-01 certificates.
- [Subscriptions](guides/subscription.md) — four formats and share links.
- [CLI reference](reference/cli.md)
- [API reference](reference/api.md)
- [Design system](design-system.md)
- [Security model](security/threat-model.md)

## Scope

The locked v0.1.0 scope is in [`PLAN.md`](https://github.com/ThzxxArt/Ostium/blob/main/PLAN.md). It includes server
Reality/Hysteria2/Trojan/SS2022, per-user quotas, ACME, four subscription
formats, client mixed/system-proxy/TUN, full Web UI/CLI, Docker, installers,
tests and release gates. It intentionally does not include NaiveProxy, a
standalone kill switch, native mobile apps, multi-node orchestration, RBAC,
DNS-01/TLS-ALPN-01 or silent auto-updates.
