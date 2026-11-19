# Ostium Server 0.2.9 — Release Notes

Ostium 0.2.9 fixes Clash / Mihomo subscriptions overriding client DNS and
breaking every domain lookup.

## Root cause

The generated Clash profile contained:

```yaml
dns:
  nameserver:
    - https://1.1.1.1/dns-query
    - https://8.8.8.8/dns-query
  proxy-server-nameserver:
    - https://1.1.1.1/dns-query
```

Clash Verge Rev detects a profile-level DNS section and disables its own DNS
override. On networks where `https://1.1.1.1/dns-query` is unreachable, every
domain resolution timed out, so all four inbounds appeared broken.

## Fixed

- Clash / Mihomo profiles no longer include a `dns` section. The client keeps
  its own DNS override and resolver settings.
- Clash profiles now contain only proxies, proxy groups and rules. They no
  longer override client-owned settings such as `mixed-port`, `mode`, `ipv6`,
  `log-level`, `allow-lan` or `bind-address`.
- Removed the `GEOIP,CN,DIRECT` rule, which required an external MMDB database.
  `DOMAIN-SUFFIX,cn,DIRECT` keeps Chinese domains direct without extra data.
- sing-box profiles no longer force DoH or `default_domain_resolver`; they use
  the client/system resolver.
- Added regression tests: generated profiles must not contain `dns`,
  `1.1.1.1`, `mixed-port` or GeoIP rules.
- Real connectivity verified through Mihomo (all four inbounds), sing-box (all
  four) and Xray (VLESS Reality, Trojan, SS2022). All egress IPs were the
  server IP.
- Server-side 443/TCP, 443/UDP, 9443/TCP and 8388/TCP are listening and
  reachable from outside.

## Client action

After upgrading, update the subscription in Clash Verge (or re-import the
Clash link), then restart the Clash core. If Clash Verge previously turned off
“DNS 覆写”, turn it back on (or restore its default DNS settings), because the
new profile no longer supplies DNS.

## Verification

```text
26 targeted tests passed
378+ full suite passed
mihomo config check passed
sing-box config check passed
```

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

```bash
pip install ostium-ctl==0.2.9
docker pull ghcr.io/thzxxart/ostium-server:0.2.9
```

## Upgrade

0.2.0–0.2.8 can upgrade in place:

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --version 0.2.9
```

## Published channels

- PyPI: https://pypi.org/project/ostium-ctl/0.2.9/
- GHCR: `ghcr.io/thzxxart/ostium-server:0.2.9` and `:latest`
- GitHub Release: `v0.2.9`
