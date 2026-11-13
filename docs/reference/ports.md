# 端口与路径

## 服务端

| 用途 | 值 |
|---|---|
| Reality / Trojan | `0.0.0.0:443/tcp` |
| Hysteria2 | `0.0.0.0:443/udp` |
| SS2022（默认关闭） | `0.0.0.0:8388/tcp+udp` |
| 管理 UI | `127.0.0.1:8443`（公网时 HTTPS） |
| ACME | 签发期间 `0.0.0.0:80/tcp` |
| 核心 API | `127.0.0.1:8788` |
| Clash API | `127.0.0.1:19090` |
| V2Ray 统计 | `127.0.0.1:19091` |

数据：`/var/lib/ostium`。配置：`/etc/ostium/config.toml`。证书：`/var/lib/ostium/certs/<domain>/`。备份：`/var/lib/ostium/backups/`。

管理 UI 默认只监听 `127.0.0.1:8443`。非回环明文监听必须显式
`allow_insecure_bind = true`；公网部署优先使用 Nginx TLS 或 Public UI，并在 Settings
中配置 `ui_allowlist`（CIDR）。Docker 必须由宿主机防火墙限制 8443。

## 客户端

| 用途 | 值 |
|---|---|
| 混合代理（默认） | `127.0.0.1:7890` |
| 混合代理（Allow LAN） | `0.0.0.0:7890`，仅可信局域网 |
| Web UI | `127.0.0.1:8787` |
| 核心 API | `127.0.0.1:8788` |
| Clash API | `127.0.0.1:19090` |
| TUN | `ostium0` / `Ostium` |

## 数据目录

| 平台 | 控制面 / UI | 核心 |
|---|---|---|
| Linux 服务端 | `/var/lib/ostium`、`/etc/ostium/config.toml` | 同左 |
| Linux 客户端 | `~/.local/share/ostium`（默认）；root 模式 `/var/lib/ostium` | `/var/lib/ostium-core`、`/etc/ostium/client.toml` |
| Windows | `%ProgramData%\Ostium`（UI） | `%ProgramData%\OstiumCore`（仅 SYSTEM/Administrators 可写） |
| macOS | `/Library/Application Support/Ostium UI`（UI） | `/Library/Application Support/Ostium` |

关键文件：`ostium.db`、`master.key`、`config.toml`、`certs/`、`runtime/last-good.json`、`runtime/core.token`、`logs/`、`backups/`。
