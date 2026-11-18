# 设置项参考

## 环境变量

完整列表见 [配置](../configuration.md)。生产必填：

- `OSTIUM_SECRET_KEY`
- `OSTIUM_FIELD_KEY`
- `OSTIUM_ALLOWED_HOSTS`
- `OSTIUM_SINGBOX_PATH`

## Constance

| key | 类型 | 默认 | 影响 |
|---|---|---|---|
| `server_name` | str | Ostium | 订阅标题 |
| `public_host` | str | 空 | 订阅节点域名 |
| `public_base_url` | str | 空 | 订阅 URL |
| `subscription_update_interval` | int | 24 | 小时 |
| `server_dns_mode` | str | auto | auto/doh/udp |
| `server_dns_doh_url` | str | 1.1.1.1 | DoH |
| `block_private_egress` | bool | true | 私网 ACL |
| `traffic_retention_days` | int | 90 | 流量保留 |
| `audit_retention_days` | int | 365 | 审计保留 |
| `log_level` | str | info | sing-box 日志 |
| `auto_backup_enabled` | bool | false | 自动备份 |
| `auto_backup_keep` | int | 7 | 保留份数 |
| `webhook_url` | str | 空 | 告警 webhook |
| `webhook_secret` | str | 空 | HMAC |
| `maintenance_mode` | bool | false | 暂停应用 |

## 安全相关 Django 设置

| 设置 | 生产值 |
|---|---|
| `DEBUG` | false |
| `SESSION_COOKIE_SECURE` | true |
| `CSRF_COOKIE_SECURE` | true |
| `SECURE_SSL_REDIRECT` | true（经代理时） |
| `SECURE_HSTS_SECONDS` | 31536000 |
| `SECURE_CSP` | self + nonce |
| `X_FRAME_OPTIONS` | DENY |
| `SECURE_REFERRER_POLICY` | no-referrer |

## 数据库

```text
SQLite:      sqlite:////var/lib/ostium/ostium.db
PostgreSQL:  postgres://user:pass@host:5432/ostium
```

SQLite 使用 WAL、`busy_timeout=30`、`IMMEDIATE` 事务。
