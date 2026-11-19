# Ostium Server 0.2.12 — Release Notes

Ostium 0.2.12 focuses on line stability and anti-blocking controls.

## Added

- **线路健康** page and `ostium inbound check [--json]`:
  - TCP/UDP listening checks;
  - certificate, key and port validation;
  - Hysteria2 salamander recommendation.
- Worker alert `inbound_unhealthy` when an enabled inbound port is not
  listening; it resolves automatically after recovery.
- Console and CLI actions to move an inbound to a random high port
  (`randomize-port`).
- Console and CLI action to rotate the VLESS Reality camouflage target
  (`rotate-camouflage`), selecting a reachable TLS target.
- Anti-blocking documentation covering high-port rotation, Reality SNI
  rotation, Hysteria2 obfs and multi-line fallback.

## Changed

- Hysteria2's key-rotation button is labelled “轮换混淆”.
- Mobile inbound action buttons wrap instead of overflowing.
- Inbound health skips the first 15 seconds after sing-box start to avoid
  startup race alerts.

## Verification

```text
422 passed, 3 skipped
coverage 90.10%
UI 8 passed
63 screenshots
```

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

```bash
pip install ostium-ctl==0.2.12
docker pull ghcr.io/thzxxart/ostium-server:0.2.12
```

## Upgrade

0.2.0–0.2.11 can upgrade in place:

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --version 0.2.12
```

## Published channels

- PyPI: https://pypi.org/project/ostium-ctl/0.2.12/
- GHCR: `ghcr.io/thzxxart/ostium-server:0.2.12` and `:latest`
- GitHub Release: `v0.2.12`
