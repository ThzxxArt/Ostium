# Ostium 文档

Ostium 是**双角色私人 VPN / 通用代理控制台**：同一个 Python 包可以装到服务器，也可以装到你的电脑；服务端和客户端共用一套 Web UI、CLI 和安装器。数据面是固定版本的 sing-box，控制面是 FastAPI + Vue 3。

> 文档以中文为主。英文概览见 [`README.en.md`](https://github.com/ThzxxArt/Ostium/blob/main/README.en.md)。

## 从这里开始

- [一键安装（推荐）](guides/install.md) — 不预装 Python，一条命令完成安装
- [服务管理](guides/service-manager.md) — systemd、OpenRC、runit、s6、supervisord、root 模式
- [Nginx 共存与反向代理](guides/nginx.md) — 80/443 被 Nginx 占用时的完整方案
- [架构](architecture.md) — 进程、端口、信任边界
- [服务端指南](guides/server.md) — Ubuntu / Debian 服务器
- [客户端指南](guides/client.md) — Windows、macOS、Linux
- [TUN 指南](guides/tun.md) — 权限、路由与已知限制
- [ACME 指南](guides/acme.md) — HTTP-01 证书
- [订阅格式](guides/subscription.md) — 四种格式与分享链接
- [Web UI 指南](guides/ui.md) — 页面、快捷键、命令面板
- [CLI 参考](reference/cli.md)
- [API 参考](reference/api.md)
- [设计系统](design-system.md)
- [安全模型](security/threat-model.md)

## v0.1.0 范围

锁定范围见 [`PLAN.md`](https://github.com/ThzxxArt/Ostium/blob/main/PLAN.md)：

- 服务端：Reality、Hysteria2、Trojan、Shadowsocks 2022
- 每用户配额、到期禁用、流量统计
- ACME HTTP-01、手动证书、自签证书
- 四种订阅格式、分享链接、二维码
- 客户端：混合代理、系统代理、TUN、URLTest、多订阅
- 完整 Web UI、CLI、Docker、安装器、测试与发布门禁

v0.1.0 **不包含**：NaiveProxy、独立 kill switch、原生手机 App、多节点编排、RBAC、DNS-01/TLS-ALPN-01、静默自动更新。
