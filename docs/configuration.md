# 配置

配置分两层：

1. **环境变量**：启动时读取，包含密钥、数据库、监听地址等。
2. **运行时设置**：保存在数据库（Constance），在控制台「设置」页修改，保存后自动应用。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `OSTIUM_SECRET_KEY` | 无（生产必填） | Django 签名密钥 |
| `OSTIUM_FIELD_KEY` | 无（生产必填） | 32 字节 base64，字段加密密钥 |
| `OSTIUM_DEBUG` | `false` | 仅开发使用 |
| `OSTIUM_DATA_DIR` | `./var` | 数据目录 |
| `OSTIUM_DB_URL` | `sqlite:///<data>/ostium.db` | 数据库 URL |
| `OSTIUM_ALLOWED_HOSTS` | `127.0.0.1,localhost,[::1]` | Django Host 白名单 |
| `OSTIUM_CSRF_TRUSTED_ORIGINS` | 空 | 公网 HTTPS 源 |
| `OSTIUM_PUBLIC_BASE_URL` | 空 | 订阅/控制台公网基址 |
| `OSTIUM_BEHIND_PROXY` | `false` | 信任 Caddy 的 `X-Forwarded-*` |
| `OSTIUM_REQUIRE_TOTP` | `false` | 强制管理员 TOTP |
| `OSTIUM_SECURE_COOKIES` | `true` | 生产 Cookie Secure |
| `OSTIUM_SINGBOX_PATH` | `.cache/bin/sing-box` | sing-box 绝对路径 |
| `OSTIUM_SINGBOX_BINARY_SHA256` | 空 | 启动时校验二进制 |
| `OSTIUM_LOG_LEVEL` | `INFO` | 应用日志级别 |
| `OSTIUM_BACKUP_PASSWORD` | 空 | 自动备份密码（可选） |

生成密钥：

```bash
openssl rand -hex 32          # OSTIUM_SECRET_KEY
openssl rand -base64 32       # OSTIUM_FIELD_KEY
```

## 运行时设置

| 设置 | 默认 | 说明 |
|---|---|---|
| `server_name` | `Ostium` | 订阅标题与界面显示名 |
| `public_host` | 空 | 订阅中宣告的域名/IP |
| `public_base_url` | 空 | 订阅 URL 基址 |
| `subscription_update_interval` | `24` | 客户端建议更新间隔（小时） |
| `server_dns_mode` | `auto` | `auto` / `doh` / `udp` |
| `server_dns_doh_url` | `https://1.1.1.1/dns-query` | DoH 端点 |
| `block_private_egress` | `true` | 阻止私网/回环/metadata 出口 |
| `log_level` | `info` | sing-box 日志级别 |
| `traffic_retention_days` | `90` | 日流量保留天数 |
| `audit_retention_days` | `365` | 审计保留天数 |
| `auto_backup_enabled` | `false` | 每日自动备份 |
| `auto_backup_keep` | `7` | 自动备份保留数量 |
| `webhook_url` | 空 | 告警 webhook（HTTPS） |
| `webhook_secret` | 空 | webhook HMAC 密钥 |
| `maintenance_mode` | `false` | 暂停配置应用 |

### DNS 模式

- **auto**：探测 DoH；成功用 DoH，失败回退 UDP 并告警。
- **doh**：DoH 不可达时拒绝应用配置（fail closed）。
- **udp**：不探测，始终使用 UDP。

### 出口 ACL

默认拒绝：

- RFC1918、CGNAT、loopback、link-local、组播/保留地址；
- 云 metadata：`169.254.169.254`、`100.100.100.200`、`fd00:ec2::254`；
- SMTP 25/tcp。

`block_private_egress=false` 只关闭私网阻断，SMTP 25 仍然阻断。

## 修改配置的推荐方式

1. 控制台「设置」页修改 → 保存 → worker 自动应用。
2. 环境变量修改后重启服务：

```bash
sudo systemctl restart ostium-web ostium-worker ostium-jobs
```

修改 `OSTIUM_FIELD_KEY` 必须使用：

```bash
sudo systemctl stop ostium-web ostium-worker ostium-jobs
sudo -u ostium /opt/ostium/venv/bin/ostium rotate_field_key --new-key '...'
# 更新 /etc/ostium/ostium.env 后启动
```
