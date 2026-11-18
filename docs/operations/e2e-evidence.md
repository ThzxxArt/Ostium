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

生产验收应在 systemd 或容器中绑定 443，并使用真实公网出口。
