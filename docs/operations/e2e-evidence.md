# E2E 验证记录

本页记录 0.2.0 发布候选在开发主机上的真实代理验证。测试环境无法以普通用户绑定 443，
因此 VLESS 使用 8443；systemd 单元通过 `CAP_NET_BIND_SERVICE` 在生产环境绑定 443。

## 环境

- Debian GNU/Linux 13 (trixie), x86_64
- Python 3.14.5, Django 6.1.3
- sing-box 1.14.4，构建标签：
  `with_quic,with_utls,with_clash_api,with_v2ray_api,badlinkname,tfogo_checklinkname0`
- 本地 TLS 目标（Reality handshake）运行在 `127.0.0.1:18443`
- 本地 HTTP 源站运行在 `127.0.0.1:18080`
- Ostium 服务端 VLESS Reality：`0.0.0.0:8443`
- 客户端 mixed 入站：`127.0.0.1:7891`

## 正常流量

```bash
curl --noproxy '' -x http://127.0.0.1:7891 http://127.0.0.1:18080/
```

输出：

```text
ostium-e2e-ok
```

V2Ray stats：

```text
{'alice': (79, 199)}
```

60 秒 flush 后：

```text
alice used_bytes 1112 last_seen 2026-11-18T08:47:19Z
```

（`834` 为此前测试累计值，本次增量 `79 + 199 = 278`。）

## 超配额

创建 10 字节配额用户 `quotauser`，通过独立客户端端口 `7892` 发送请求后：

```text
name             quotauser
enabled          False
status           quota_exceeded
used_bytes       834
quota_bytes      10
subscription HTTP: 403
```

即：真实流量 → stats 增长 → DB flush → 配额检查禁用用户 → 订阅返回 403。

## 契约校验

```text
sing-box check 服务端配置: pass
sing-box check sing-box 订阅: pass
mihomo -t Clash 订阅: pass
```

## 复现

1. 初始化 Ostium，启用 VLESS，端口改为 8443。
2. 运行 worker 与本地 TLS/HTTP 测试目标。
3. 拉取 `?target=singbox` 订阅，启动 sing-box 客户端。
4. 通过客户端代理访问源站。
5. 等待 60 秒 flush，查询 `used_bytes` 与 `/sub/<token>`。

## 2026-11-18 复验：Trojan 自签证书 pin + 配额

在修复自签证书 pin、统计 flush 与 pending 配额后重新执行：

- 临时数据目录，Trojan inbound `0.0.0.0:8443`，自签证书 `localhost`
- 客户端 sing-box 使用订阅生成的 `tls.certificate_public_key_sha256`
- Clash/V2Ray 端口使用 `29090/29091`，避免与开发机已有实例冲突

```text
PROXY_BODY=<!doctype html><html lang=en><head>...
E2E_USED=2016
QUOTA_STATE=False quota_exceeded 1008
QUOTA_SUB=403
E2E_OK
```

即：自签 Trojan 客户端在仅 pin SPKI 的情况下真实连接成功；代理流量写入
`used_bytes`；10 字节配额用户在真实流量后被禁用，订阅返回 403。

## 2026-11-18 发布前复验：新构建 + 实时统计

在发布前回归中使用本轮重新构建的 sing-box `v1.14.4`（Go 1.27.4）再次执行：

- 临时数据目录，Trojan `0.0.0.0:8443`，自签证书 `localhost`
- 客户端订阅使用 `tls.certificate_public_key_sha256` 做 SPKI pin
- 客户端 mixed 入站 `127.0.0.1:7891`
- 真实访问 `http://example.com/`

```text
CURL_RC 0
BODY_PREFIX <!doctype html><html lang=en><head><meta charset=utf-8><link rel=icon href=data:
STATS {'e2e': (75, 933)}
PIN g0Ob/WAR7I1C6AUc
E2E_OK
```

即：真实 Trojan 自签连接成功，V2Ray stats 立即记录到 `75` 上行 /
`933` 下行字节。超配额 403 的历史证据仍见上一节。

生产验收仍应在 systemd 或容器中绑定 443，并使用真实公网出口。
