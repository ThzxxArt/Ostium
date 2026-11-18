# Ostium Server

Ostium 0.2.1 是一个 **Linux 单机、单管理员、私人代理服务端**。
它把管理面（Django + Aurora Console）和数据面（sing-box）放在同一台主机上，
对外只暴露一条标准订阅链接和代理端口。

## 它是什么

- 四条线路：VLESS Reality、Hysteria2、Trojan、Shadowsocks 2022。
- 四种标准订阅：Base64 URI、Clash/Mihomo YAML、sing-box JSON、纯 URI。
- 现代管理控制台：实时状态、流量图、配额环、连接、证书、日志、任务、审计。
- 单二进制数据面：worker 直接监督 pinned sing-box，没有自研 core API。
- 默认安全：管理面只监听 `127.0.0.1:8000`，公网访问要求 TLS + TOTP。

## 它不是什么

- 不是桌面/手机客户端，不包含 TUN、系统代理、kill switch。
- 不是多节点编排、CDN、多租户或 RBAC 平台。
- 不读取或迁移 0.1.x 的数据库、配置、证书、token。
- 不提供私有订阅格式；客户端只使用通用标准。

## 30 秒了解

```text
浏览器 -> Caddy(8443, TLS) -> Django(127.0.0.1:8000) -> SQLite/PostgreSQL
                                                   |
                                             worker -> sing-box(443)
                                                   |
客户端 -> /sub/<token> -> 标准订阅 -> sing-box 客户端 -> 443 -> 出口
```

## 下一步

- [快速开始](getting-started.md)：从源码启动一个开发实例。
- [从零部署教程](tutorials/from-zero.md)：systemd + Caddy、Docker + Caddy、SSH 隧道。
- [安装](installation.md)：systemd 或 Docker Compose。
- [订阅](subscriptions.md)：把链接导入 v2rayN、Clash Verge、sing-box。
- [安全](security.md)：公网暴露前的检查清单。

## 质量记录

- [0.2.0 发布前验收矩阵](review/0.2.0-pre-release-audit.md)
- [0.2.0 发布前全量回归](review/0.2.0-pre-release-regression.md)
- [0.2.0 完成度审计（历史）](review/0.2.0-completion-audit.md)
- [0.2.0 全量回归报告（历史）](review/0.2.0-regression-report.md)

## 版本与许可

当前版本 `0.2.1`，AGPL-3.0-or-later。旧版本只存在于 git 历史与 `v0.1.12` tag。
