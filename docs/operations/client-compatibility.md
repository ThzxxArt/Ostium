# 客户端兼容性

Ostium 只生成标准订阅，不要求私有客户端。本文记录实际验证过的客户端、协议矩阵
和常见问题。

## 已验证矩阵

测试日期：2026-11-19

| 客户端 | 版本 | VLESS Reality | Hysteria2 | Trojan | SS2022 |
|---|---|---|---|---|---|
| Mihomo | v1.19.34 | ✅ | ✅ | ✅ | ✅ |
| sing-box | v1.14.4 | ✅ | ✅ | ✅ | ✅ |
| Xray | v26.11.9 | ✅ | Xray 不支持 | ✅ | ✅ |

验证方式不是只看配置语法，而是：

1. 启动本地 sing-box 服务端；
2. 启动真实客户端；
3. 通过代理访问 `https://example.com`，断言 HTTP 200；
4. Mihomo / sing-box 分别测试全部四条线路，Xray 测试其支持的三种协议。

复现：

```bash
OSTIUM_E2E=1 OSTIUM_XRAY_PATH=.cache/bin/xray \
  uv run pytest tests/e2e/test_client_matrix.py -q
```

## 推荐订阅

| 客户端 | 推荐链接 |
|---|---|
| Mihomo / Clash Verge Rev / OpenClash | `/sub/<token>/clash` |
| sing-box 官方客户端 | `/sub/<token>/singbox` |
| v2rayN / v2rayNG / Shadowrocket / NekoBox | `/sub/<token>`（Base64 URI） |
| 手动导入 / 调试 | `/sub/<token>?target=uri` |

## DNS 行为

Clash / Mihomo 订阅默认**不包含** `dns` 段，sing-box 订阅默认不设置 DNS
resolver。这样：

- 客户端自己的 DNS 覆写开启或关闭都可以工作；
- 订阅不会触发 Clash Verge 的“订阅修改 DNS”提示；
- 不会强制使用不可达的公共 DoH。

如果客户端自身 DNS 被设置为不可达的服务器，任何订阅都无法解析域名。请改用系统
DNS 或可达的国内 DNS（例如 `223.5.5.5`、`119.29.29.29`）。

自 0.2.9 起也不再写入 `mixed-port`、`mode`、`ipv6`、`log-level` 等客户端设置；
端口和运行模式由客户端自己决定。

## 不依赖 GeoIP 数据库

默认规则使用 `DOMAIN-SUFFIX,cn,DIRECT`，不使用 `GEOIP` / `GEOSITE`。缺少
`geoip.metadb` / `geosite.dat` 的客户端不会因此拒绝加载配置。

## 常见问题

### `dns resolve failed`

订阅不再包含 DNS。请检查客户端自己的 DNS 设置，不要指向不可达的 DoH。
更新时间较旧的配置后，建议删除旧 profile 再重新导入。

### Hysteria2 无法连接

Hysteria2 使用 UDP/QUIC。确认网络/防火墙允许 UDP 443；如果网络限制 UDP，改用
VLESS Reality 或 Trojan。

### SS2022 无法导入

Shadowsocks 2022 需要较新的客户端。旧客户端请使用 VLESS Reality 或 Trojan。

### 导入后没有流量

在控制台「订阅」页打开「订阅自检」，确认结构检查通过；再检查客户端是否选择了
`Ostium` 组，以及服务端端口 443/9443/8388 是否可达。

### Clash Verge 提示“订阅修改 DNS”

0.2.9 及以后不会再出现。若仍出现，说明客户端还在使用旧 profile，请重新导入。
