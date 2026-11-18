# 安全

## 管理面

| 控制 | 实现 |
|---|---|
| 密码 | Argon2id |
| 会话 | HttpOnly、SameSite=Lax、生产 Secure |
| CSRF | Django CSRF |
| 两步验证 | django-otp TOTP + 恢复码 |
| 登录锁定 | django-axes，5 次 / 15 分钟 |
| 限速 | django-ratelimit |
| CSP | Django 6.1 Content Security Policy |
| Host | `ALLOWED_HOSTS` + `CSRF_TRUSTED_ORIGINS` |
| 点击劫持 | `X-Frame-Options: DENY` |
| MIME | `X-Content-Type-Options: nosniff` |
| Referrer | `same-origin`（订阅响应强制 `no-referrer`） |
| 默认监听 | `127.0.0.1:8000` |
| 审计 | `AuditEvent` + django-auditlog |

### 公网暴露清单

- [ ] Caddy/反向代理启用 TLS。
- [ ] `OSTIUM_BEHIND_PROXY=true`、`OSTIUM_SECURE_COOKIES=true`。
- [ ] `OSTIUM_REQUIRE_TOTP=true`，管理员已绑定 TOTP。
- [ ] `OSTIUM_ALLOWED_HOSTS` 只包含真实域名。
- [ ] `OSTIUM_CSRF_TRUSTED_ORIGINS` 使用 HTTPS。
- [ ] 防火墙只放行 443/tcp、443/udp、8443/tcp 与 SSH。
- [ ] `ostium doctor` 无 fail。

## 订阅面

- 32 字节 token；SHA-256 哈希 + AES-GCM 加密副本。
- 未知 token 404，不泄露用户是否存在。
- 禁用/到期/超配额 403。
- `Cache-Control: private, no-store`、`Referrer-Policy: no-referrer`、`X-Robots-Tag: noindex`。
- 每 IP 60 次/分钟；每 token 120 次/分钟。
- 日志与审计不记录完整 token。

## 数据面

- sing-box 固定 tag + SHA256 + 最小构建标签。
- 只执行固定 argv；配置由数据库生成。
- `sing-box check` 通过后才替换；失败回滚。
- 非 root，仅 `CAP_NET_BIND_SERVICE`。
- 出口 ACL：私网、CGNAT、回环、link-local、云 metadata、SMTP 25。
- Clash API / V2Ray stats 仅回环，secret 0600。

## 字段加密

- `OSTIUM_FIELD_KEY`：32 字节 base64，AES-256-GCM。
- AAD 绑定 `app.model:pk:field`；UUID 主键。
- 轮换使用 `ostium rotate_field_key`（离线）。
- 备份整体加密；未加密需要显式确认。

## 供应链

- `uv.lock` 锁定依赖。
- `pip-audit`、`bandit`、`django check --deploy`。
- sing-box 构建产出 SHA256 与 SBOM。
- Docker 基础镜像固定；容器非 root、只读根文件系统。

## 残余风险

- web 与 worker 使用同一系统用户；web 被攻破可影响 worker。
- worker 重启时隧道短暂中断。
- certbot/Caddy 是外部依赖。
- 自签证书的客户端兼容性取决于客户端。
- 0.1.x 数据不迁移；旧用户需要重建。
