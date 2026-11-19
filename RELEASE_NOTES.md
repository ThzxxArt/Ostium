# Ostium Server 0.2.10 — Release Notes

Ostium 0.2.10 is a client-compatibility quality release. It turns the manual
0.2.9 Clash/Mihomo checks into an automated real-client matrix and adds
self-check tooling.

## Added

- Real-client E2E matrix:
  - Mihomo v1.19.34: VLESS Reality, Hysteria2, Trojan, SS2022
  - sing-box v1.14.4: all four inbounds
  - Xray v26.11.9: VLESS Reality, Trojan, SS2022
  - The harness starts a local server and Reality TLS target, runs real clients
    and verifies egress through `https://example.com`.
- `ProfileOptions` policy object. Defaults remain client-owned DNS, no client
  port/mode overrides and no external GeoIP database.
- `ostium subscription check --user <name> [--json] [--no-binaries]`.
- Console **订阅兼容性自检** page, linked from subscriptions and user detail.
- Dashboard first-deploy checklist: user, inbound, certificate, backup,
  webhook, TOTP.
- Client compatibility documentation and DNS troubleshooting.

## Changed

- Clash profiles contain only `proxies`, `proxy-groups` and `rules` by default.
- New `tests/e2e` CI job runs the real-client matrix.

## Verification

```text
395 passed, 3 skipped
coverage 90.31%
UI 8 passed
real-client E2E: Mihomo 4/4, sing-box 4/4, Xray 3/3
```

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

```bash
pip install ostium-ctl==0.2.10
docker pull ghcr.io/thzxxart/ostium-server:0.2.10
```

## Upgrade

0.2.0–0.2.9 can upgrade in place:

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --version 0.2.10
```

## Published channels

- PyPI: https://pypi.org/project/ostium-ctl/0.2.10/
- GHCR: `ghcr.io/thzxxart/ostium-server:0.2.10` and `:latest`
- GitHub Release: `v0.2.10`
