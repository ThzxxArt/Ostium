# 监控

## 端点

| 端点 | 用途 |
|---|---|
| `/healthz` | 进程存活，始终 200 |
| `/readyz` | DB + worker 心跳 + sing-box 状态 |
| `/metrics` | Prometheus 指标 |
| `/health/` | django-health-check（DB/cache/storage） |

`/readyz` 在数据库不可用时返回 503；worker/sing-box 异常时返回 200 + `degraded`，
便于区分“进程挂了”和“数据面降级”。Caddy 只允许本机访问 `/metrics`、
`/readyz` 与 `/health/`；Prometheus 应直接抓取 `127.0.0.1:8000`。

## Prometheus 指标

```text
ostium_worker_alive
ostium_singbox_running
ostium_active_users
ostium_online_users
ostium_unacknowledged_alerts
ostium_disk_free_bytes
```

示例抓取配置：

```yaml
scrape_configs:
  - job_name: ostium
    static_configs:
      - targets: ["127.0.0.1:8000"]
    metrics_path: /metrics
```

## 审计事件

自动备份成功/失败会写入审计：

```text
backup.created
backup.failed
```

「审计」页可以按时间、目标查看，不再只依赖「系统 → 最近备份」。

## 告警码

| code | 含义 |
|---|---|
| `worker_down` | worker 心跳超时 |
| `singbox_down` | sing-box 未运行 |
| `config_apply_failed` | 配置生成/校验/启动失败 |
| `stats_unavailable` | V2Ray 统计超过 5 分钟不可用 |
| `certificate_expiring` | 证书 ≤30 天 |
| `certificate_expired` | 证书已过期 |
| `disk_low` | 数据盘 <1 GiB |
| `inbound_unhealthy` | 已启用线路端口未监听或配置异常 |
| `backup.created` | 审计事件：自动备份已创建 |
| `backup.failed` | 审计事件：自动备份失败 |
| `quota_80` / `quota_90` | 用户配额阈值 |
| `backup_failed` | 自动备份失败 |
| `dns_fallback` | DoH 失败回退 UDP |

告警在控制台总览与「系统」页展示；可在 API/Admin 确认。

## Webhook

设置 `webhook_url` 与 `webhook_secret`。请求体 JSON，HMAC-SHA256 签名放在
`X-Ostium-Signature`（`sha256=<hex>`）。只允许 HTTPS，发送前解析目标并拒绝
私网、回环、link-local、CGNAT、metadata 与保留地址；最多重试 3 次。
告警确认后不会因周期性重复触发而重新打开；恢复后再次出现会重新通知。

## 日志

- 应用：`/var/lib/ostium/logs/ostium.log`（同时输出到 journald）。
- 数据面：`/var/lib/ostium/logs/sing-box.log`。
- 控制台「日志」最多读取 2 MiB 尾部；下载按钮导出当前内容。
- 诊断包自动脱敏。

```bash
journalctl -u ostium-worker -f
tail -f /var/lib/ostium/logs/sing-box.log
```
