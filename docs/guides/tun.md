# TUN guide

TUN mode gives Ostium a virtual interface and captures TCP, UDP and DNS traffic
from the whole machine. It is powerful and requires elevated privileges.

## Parameters

| Setting | Value |
|---|---|
| Interface | `ostium0` (Linux/macOS), `Ostium` (Windows) |
| Addresses | `172.19.0.1/30`, `fdfe:dcba:9876::1/126` |
| MTU | 1500 (advanced: up to 9000) |
| Stack | `gvisor` by default; `system`/`mixed` optional |
| DNS | `hijack` via the core DNS module |
| Route | `auto_route`, `strict_route`, RFC1918/link-local exclusions |
| IPv6 | Enabled by default; can be disabled per profile |

## Permissions

- **Windows**: `OstiumCore` service runs as LocalSystem. Wintun DLL ships beside
  the core binary.
- **macOS**: LaunchDaemon runs as root and uses `utun`.
- **Linux**: system user `ostium-core` with `CAP_NET_ADMIN`, `CAP_NET_RAW` and
  access to `/dev/net/tun`.

The Web UI never runs with these privileges. It talks to the core over a
token-protected loopback API.

## Switching modes

System proxy and TUN are mutually exclusive. Enabling TUN first disables the
system proxy. If TUN fails, Ostium reports the error and does **not** silently
fall back to system proxy, because that would create a false sense of full
coverage.

Disabling TUN reloads a mixed-only configuration and lets sing-box remove its
routes and interface. If the core is killed, the OS may remove the routes
automatically; check **Diagnostics** after a crash.

## Kill switch boundary

`strict_route` prevents common leaks while TUN is running, but Ostium v0.1.0
does **not** ship a standalone firewall kill switch. If the core exits, direct
connectivity can return. This is shown in the UI and is an explicit v0.1.0
boundary, not a deferred feature.

## DNS

In TUN mode, DNS queries are hijacked by the core. Smart routing resolves
Chinese domains through a local resolver and everything else through a remote
DoH server over the proxy. In mixed/system-proxy mode, applications resolve DNS
themselves; the UI warns that DNS is not taken over.

## Troubleshooting

- `permission denied` / `tun: operation not permitted`: the core service is not
  running with the required capability.
- `address already in use`: another VPN/TUN client is active.
- No connectivity after disconnect: run Diagnostics; restart the core to clean
  routes if the previous process crashed.
