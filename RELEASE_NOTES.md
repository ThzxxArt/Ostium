# Ostium Server 0.2.13 — Release Notes

Ostium 0.2.13 hardens UDP/Hysteria2 stability and adds a TCP-only fallback
group so a flaky UDP path does not take down the whole subscription.

## Added

- Installer and upgrade automatically raise and persist UDP buffers:
  `net.core.rmem_max` / `wmem_max` to at least 16 MiB.
- `ostium doctor` checks UDP buffer size and Hysteria2 health.
- Clash subscriptions add a **Stable** `fallback` group containing only TCP
  inbounds (Reality, Trojan, SS2022). sing-box adds the matching selector.
- Automatic backups now write `backup.created` / `backup.failed` audit events.
- Hysteria2/UDP troubleshooting and Stable-group documentation.

## Fixed

- The doctor's no-TOTP branch now constructs its check correctly.

## Verification

```text
full test suite passes
coverage >= 90%
UI checks pass
Mihomo config contract passes
```

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

```bash
pip install ostium-ctl==0.2.13
docker pull ghcr.io/thzxxart/ostium-server:0.2.13
```

## Upgrade

0.2.0–0.2.12 can upgrade in place:

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --version 0.2.13
```

## Published channels

- PyPI: https://pypi.org/project/ostium-ctl/0.2.13/
- GHCR: `ghcr.io/thzxxart/ostium-server:0.2.13` and `:latest`
- GitHub Release: `v0.2.13`
