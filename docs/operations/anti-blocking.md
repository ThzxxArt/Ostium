# 线路稳定性与防封禁

Ostium 的四条线路是互备关系。本文记录控制台里的健康检查和防封禁操作。

## 线路健康

控制台「线路 → 线路自检」会检查每条已启用线路：

- 端口是否按协议在监听（TCP/UDP）；
- 证书是否存在且就绪；
- Reality 密钥、Shadowsocks 2022 密钥是否存在；
- Hysteria2 是否启用 salamander 混淆；
- 配置是否通过模型校验。

命令行：

```bash
ostium inbound check
ostium inbound check --json
```

worker 每 5 分钟也会检查一次。已启用但端口未监听时会产生
`inbound_unhealthy` 告警，恢复后自动解除。

健康检查不会发送真实代理流量；它验证的是服务端监听和配置状态。

## 防封禁操作

### 随机高位端口

「线路」卡片上的「随机端口」会把该线路切换到 20000–59999 的空闲端口。

- 不会与其他 Ostium 线路或本机监听端口冲突；
- 变更后需要：
  1. 在云厂商安全组/本机防火墙放行新端口；
  2. 让客户端重新拉取订阅；
  3. 确认新端口可从外网访问。

VLESS 和 Hysteria2 默认使用 443；Trojan/Shadowsocks 更适合使用高位端口。
修改 443 前请确认不会影响现有客户端。

### Reality 伪装轮换

「线路 → Reality → 更换伪装」会从一组常见 TLS 站点中选择一个当前可达的目标：

```text
www.microsoft.com / www.apple.com / www.cloudflare.com
www.amazon.com / www.bing.com / www.samsung.com ...
```

检查方式是连接目标的 443 端口；不可达的目标会被跳过。变更后会更新：

- `server_name`
- `handshake_server`
- `handshake_port=443`

客户端需要重新导入订阅。Reality 密钥和 Short ID 不会被这个操作修改；需要
同时轮换密钥时使用「轮换密钥」。

### Hysteria2 混淆

Hysteria2 默认带 salamander 混淆。没有混淆时健康页会显示「注意」；轮换混淆
后现有客户端会失效，需要重新导入订阅。

### 多线互备

订阅中的 `Auto` 组会测速选择线路。建议至少保留：

- 一条 VLESS Reality（TCP，无证书）；
- 一条 Hysteria2（UDP/QUIC）或 Trojan（TCP/TLS）。

如果某一协议被针对性阻断，客户端仍可通过其他线路出网。

## 常见误判

- 健康页显示「未监听」但客户端可用：检查是否在看测试环境/旧数据目录；
- 健康页显示「sing-box 未运行」：先看 `ostium status` 和 worker 日志；
- 改端口后订阅仍用旧端口：客户端必须重新拉取订阅；
- 更换伪装后全部客户端失效：这是预期行为，重新导入订阅即可。
