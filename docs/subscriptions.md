# 订阅

Ostium 只提供通用标准订阅，不使用私有格式。

## 链接

```text
/sub/<token>                  Base64 URI（默认）
/sub/<token>?target=uri       纯 URI
/sub/<token>?target=clash     Clash / Mihomo YAML
/sub/<token>?target=singbox   sing-box 完整配置

/sub/<token>/v2ray            同默认
/sub/<token>/clash            同 Clash
/sub/<token>/singbox          同 sing-box
```

别名：`format=`、`flag=` 等价 `target=`；`base64` 等价默认；
`sing-box` 等价 `singbox`；`clash-meta`/`clash.meta` 等价 `clash`。

## 客户端

| 客户端 | 使用链接 |
|---|---|
| v2rayN / v2rayNG / Shadowrocket / NekoBox | 默认 Base64 |
| Clash Verge Rev / Mihomo Party / OpenClash | `?target=clash` |
| sing-box 官方客户端 | `?target=singbox` |
| 手动导入 / 调试 | `?target=uri` |

## 响应头

```http
Subscription-Userinfo: upload=...; download=...; total=...; expire=...
Profile-Update-Interval: 24
Profile-Title: <user>@<server_name>
Cache-Control: private, no-store
Referrer-Policy: no-referrer
X-Robots-Tag: noindex, nofollow
```

`total=0` 表示不限；`expire=0` 表示不过期。

## 状态码

| 情况 | 状态 |
|---|---|
| token 不存在或格式错误 | 404 |
| 用户被禁用 / 到期 / 超配额 | 403 |
| 没有可用线路 | 403 |
| 未知 target | 400 |
| 限速 | 429 + `Retry-After` |
| 正常 | 200 |

## Token 安全

- 32 字节随机 token；数据库只存 SHA-256 哈希与 AES-GCM 加密副本。
- 控制台默认打码；显示需要 POST，并写入审计。
- 轮换后旧 URL 立即失效。
- 日志、审计、诊断包不记录完整 token。

## 订阅内容

- **Base64**：每行一条分享 URI，整体 Base64。
- **Clash**：fake-IP DNS、`Ostium` 选择组、`Auto` 自动测速、私有地址直连、
  `GEOIP,CN,DIRECT`、`MATCH,Ostium`。
- **sing-box**：完整客户端配置，mixed 入站 `127.0.0.1:7890`，不启用 TUN。
- **URI**：便于复制单节点。

生成的 Clash YAML 通过 `mihomo -t`，sing-box JSON 通过 `sing-box check`。
