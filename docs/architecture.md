# 架构

Ostium 把**有特权的网络路径**和 **Web/API/数据库路径**拆成两个服务，默认不把 root/TUN 权限交给管理界面。

```text
systemd / launchd / SCM / 你的进程管理器
├─ ostium-core.service
│   ├─ ostium core-run
│   └─ sing-box（子进程，固定 1.14.4 + with_v2ray_api）
└─ ostium.service
    ├─ uvicorn（FastAPI + SPA）
    └─ 后台任务（统计、ACME、任务、备份）
```

## 控制面（`ostium.service`）

负责 FastAPI、Vue SPA、CLI、SQLite/Alembic、用户、订阅、规则、证书、ACME、备份、审计和任务系统。

- 默认**不**绑定公网代理端口，也不创建 TUN 设备。
- 服务端默认以 `ostium` 系统用户运行。
- 客户端默认以登录用户运行；root 模式可以用 `--run-as-root` 改为 root。
- 即使控制面崩溃或被升级，核心仍可保持现有隧道。

## 核心（`ostium-core.service`）

监听 `127.0.0.1:8788` 的小型 FastAPI，使用 Bearer token 保护。它：

- 只接受白名单内的 sing-box 配置；
- 按角色策略校验端口、路径和入口；
- 写入 `last-good.json`；
- 执行 `sing-box check`；
- 原子替换运行时配置，然后重启子进程并验证存活；失败回滚上一版（SIGHUP 无法证明新配置已生效，因此不再使用）；
- 不执行 shell，不连接数据库。

## 数据流

```text
客户端 App → 127.0.0.1:7890（混合代理）/ TUN
          → VLESS+Reality / Hysteria2 / Trojan / SS2022
          → 服务端 sing-box → 直连出口
```

控制面把生成的 JSON 推给核心 API。核心事务式应用：校验或启动失败时保留上一版配置。统计每 5 秒从 sing-box 的 V2Ray gRPC API 读取，每分钟写入 SQLite。

服务端路由默认拒绝 RFC1918、CGNAT、link-local、云 metadata 和 SMTP 25 出口；
`block_private_egress = false` 时仍拒绝 25。

配额和到期由控制面执行。**控制面停止时，核心继续服务现有配置，但配额执行会暂停**——这是当前版本的明确限制。

## 端口

| 组件 | 地址 |
|---|---|
| 服务端 Reality / Trojan | `0.0.0.0:443/tcp` |
| 服务端 Hysteria2 | `0.0.0.0:443/udp` |
| 服务端 SS2022（默认关闭） | `0.0.0.0:8388/tcp+udp` |
| 服务端管理 UI | 默认 `127.0.0.1:8443`；公网必须 TLS + TOTP |
| ACME HTTP-01 | 签发期间 `0.0.0.0:80/tcp` |
| 客户端混合代理 | `127.0.0.1:7890` |
| 客户端 Web UI | `127.0.0.1:8787` |
| 核心 API | `127.0.0.1:8788` |
| Clash API | `127.0.0.1:19090` |
| V2Ray 统计 | `127.0.0.1:19091` |

## 文件

- 服务端数据：`/var/lib/ostium`
- 服务端配置：`/etc/ostium`
- 客户端 UI 数据：平台用户数据目录
- Linux 客户端核心：`/var/lib/ostium-core`

`master.key`、`core.token`、`clash.secret` 等密钥权限为 0600/0640，绝不提交到仓库。

## 数据库

SQLite + WAL + 外键 + Alembic。首次启动自动建表并标记初始迁移；后续升级执行迁移。敏感字段使用 AES-256-GCM，AAD 绑定表/行/字段。

## 运行身份

默认模式：

- 控制面：`ostium` 用户（无特权）
- 服务端核心：`ostium` 用户 + `CAP_NET_BIND_SERVICE`
- 客户端核心：`ostium-core` 用户 + `CAP_NET_ADMIN` / `CAP_NET_RAW`
- 客户端 UI：登录用户

可选模式：

- `--run-as-root`：不创建服务用户，两个服务都以 root 运行。方便，但取消了控制面与 root 的隔离；Web/API 漏洞的影响面会扩大。
- `--no-service`：不注册 systemd/launchd，交给 OpenRC、runit、s6、supervisord 或手动运行。

详见 [服务管理](guides/service-manager.md)。
