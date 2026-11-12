# Ports and paths

## Server

| Purpose | Value |
|---|---|
| Reality / Trojan | `0.0.0.0:443/tcp` |
| Hysteria2 | `0.0.0.0:443/udp` |
| SS2022 (off) | `0.0.0.0:8388/tcp+udp` |
| Admin UI | `127.0.0.1:8443` (HTTPS when public) |
| ACME | `0.0.0.0:80/tcp` during issuance |
| Core API | `127.0.0.1:8788` |
| Clash API | `127.0.0.1:19090` |
| V2Ray stats | `127.0.0.1:19091` |

Data: `/var/lib/ostium`. Config: `/etc/ostium/config.toml`. Certificates:
`/var/lib/ostium/certs/<domain>/`. Backups: `/var/lib/ostium/backups/`.

## Client

| Purpose | Value |
|---|---|
| Mixed proxy | `127.0.0.1:7890` |
| Web UI | `127.0.0.1:8787` |
| Core API | `127.0.0.1:8788` |
| Clash API | `127.0.0.1:19090` |
| TUN | `ostium0` / `Ostium` |

Linux core data: `/var/lib/ostium-core`. Linux UI data:
`~/.local/share/ostium`. macOS core:
`/Library/Application Support/Ostium`; UI:
`~/Library/Application Support/Ostium`. Windows core:
`%ProgramData%\Ostium`; UI: `%LOCALAPPDATA%\Ostium`.
