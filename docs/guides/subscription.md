# 订阅

每个启用的用户都可以有一个订阅 token。token 是机密：拿到 URL 的人就能使用该用户的凭据。
订阅 URL 的基地址按以下顺序解析：Settings 的 `public_base_url` → `--domain`/server domain
派生的 `https://<domain>` → `http://127.0.0.1:<port>`。不会使用请求的 `Host` 头，因此
SSH 隧道访问也能生成客户端可用的公网 URL。

## 格式

| 格式 | URL | 用途 |
|---|---|---|
| Ostium Profile v1 | `/sub/<token>?format=ostium` | Ostium 客户端；完整元数据 |
| Base64 URI 列表 | `/sub/<token>?format=base64` | v2rayN 等兼容客户端 |
| Clash Meta YAML | `/sub/<token>?format=clash` | Clash Meta / Mihomo |
| sing-box JSON | `/sub/<token>?format=singbox` | sing-box outbounds |

响应头包含 `Cache-Control: no-store`、`Referrer-Policy: no-referrer`，并限制每 IP 每分钟 60 次。禁用、到期或超配额的用户返回 403；未知 token 返回 404；未知 `format` 返回 400。

## 管理端 API

`GET /api/v1/users/{id}/subscription` 默认只返回 `token_hint` 和 `reveal_required=true`。
需要完整 token/URL/二维码时使用 `?reveal=true`，该操作会写入审计日志。创建用户和轮换
token 时仍一次性返回完整 token。

## 导入

在 Ostium 中：**Profiles → Import**，粘贴 URL、分享链接、JSON，或扫描二维码图片。订阅型配置每天刷新一次；刷新失败时保留上一次成功副本。

第三方客户端：导出 Base64 或 Clash 格式。URL 中包含标准 VLESS/Hysteria2/Trojan/SS2022 参数。

## 轮换

在 **Subscriptions** 或用户抽屉中轮换订阅 token。旧 URL 立即失效。轮换凭据（UUID/密码）是另一个操作，会断开活跃会话。

## 安全

- 不要把订阅 URL 发到公开 issue 或截图。
- 使用公网域名时，订阅端点优先走 HTTPS。
- token 以 SHA-256 哈希 + 加密副本存储，不写入日志。
- 怀疑泄露时立即轮换，并检查审计日志。
