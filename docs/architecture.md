# 架构

## 进程

```text
systemd / Compose
├─ ostium-web      Gunicorn + Django，127.0.0.1:8000
├─ ostium-worker   worker，监督 sing-box
│   └─ sing-box    443/tcp + 443/udp（+ 8388/tcp 可选）
├─ ostium-jobs     django-q2 qcluster
├─ caddy（可选）    TLS，8443 -> 127.0.0.1:8000
└─ certbot.timer   证书续期 -> deploy hook -> ostium cert sync
```

## 数据流

```text
控制台/API -> 数据库 -> desired_revision++
worker -> 从数据库生成配置 -> sing-box check
  OK -> 停旧进程 -> 启新进程 -> 观察 -> 原子替换
  失败 -> 保留旧配置 -> 告警 -> 指数退避重试
V2Ray gRPC -> 每 5 秒采样 -> 每 60 秒写数据库
```

## 为什么没有 core API

0.1.x 的 core 服务用于客户端 TUN 的 root 隔离。0.2.0 没有客户端与 TUN，
worker 以非 root + `CAP_NET_BIND_SERVICE` 运行，直接监督 sing-box 即可。

代价：worker 重启/升级时隧道中断 1–3 秒。

## 配置可信边界

- 配置只来自数据库模型，不接受任意 JSON。
- 每次应用前执行真实 `sing-box check`。
- 配置、证书、密钥文件 0600；数据目录 0700。
- Clash API 与 V2Ray stats 只监听回环。
- 出口 ACL 阻止私网、metadata 与 SMTP 25。

## 数据库

SQLite 默认开启 WAL、`busy_timeout` 与 `IMMEDIATE` 事务。web、worker、jobs
共享同一数据库；高写入场景推荐 PostgreSQL 18。

## 订阅

订阅渲染是纯函数：`Endpoint -> URI / Clash YAML / sing-box JSON`。
无数据库写入、无管理员会话、无 Cookie。
