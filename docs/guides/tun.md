# TUN 指南

TUN 模式会让 Ostium 创建虚拟网卡，接管整机 TCP、UDP 和 DNS。它很强，但需要高权限。

## 参数

| 设置 | 值 |
|---|---|
| 网卡名 | `ostium0`（Linux/macOS）、`Ostium`（Windows） |
| 地址 | `172.19.0.1/30`、`fdfe:dcba:9876::1/126` |
| MTU | 1500（高级可到 9000） |
| 栈 | 默认 `gvisor`；可选 `system` / `mixed` |
| DNS | 由核心 DNS 模块 `hijack` |
| 路由 | `auto_route`、`strict_route`、排除 RFC1918/link-local |
| IPv6 | 默认启用；可按配置关闭 |

## 权限

- **Windows**：`OstiumCore` 服务以 LocalSystem 运行，Wintun DLL 放在核心二进制旁。
- **macOS**：LaunchDaemon 以 root 运行，使用 `utun`。
- **Linux**：`ostium-core` 用户拥有 `CAP_NET_ADMIN`、`CAP_NET_RAW` 和 `/dev/net/tun` 访问权限。

默认模式下 Web UI 永远不拥有这些权限，只通过带 token 的回环 API 与核心通信。

如果你用 `--run-as-root` 安装，核心和控制面都以 root 运行。方便，但失去了控制面与 root 的隔离；不要在没有其他隔离的生产环境使用。

## 切换模式

系统代理和 TUN 互斥。启用 TUN 会先关闭系统代理。如果 TUN 启动失败，Ostium 会报错，**不会**静默回退到系统代理，避免让你误以为已经全机接管。

关闭 TUN 会重载仅混合代理的配置，让 sing-box 清理路由和网卡。如果核心被强杀，操作系统可能自动清理路由；崩溃后请用 **Diagnostics** 检查。

## Kill switch 边界

`strict_route` 能减少 TUN 运行时的常见泄漏，但 Ostium v0.1.0 **不提供独立防火墙 kill switch**。核心退出后，直连可能恢复。UI 会明确提示，这是 v0.1.0 的边界，不是“以后再做”的功能。

## DNS

TUN 模式下 DNS 查询由核心接管：智能分流会让国内域名走本地解析器，其他流量走代理上的远程 DoH。混合代理/系统代理模式下，应用自己解析 DNS；UI 会提示“未接管 DNS”。

## 故障排查

- `permission denied` / `tun: operation not permitted`：核心服务没有所需 capability，或不是 root/SYSTEM。
- `address already in use`：另一个 VPN/TUN 客户端占用网卡或路由。
- 断开后无法上网：运行 Diagnostics；如果旧进程崩溃，重启核心清理路由。
- TUN 开启后部分应用仍直连：检查路由规则、应用是否使用自己的网络栈，以及是否启用了 `strict_route`。
