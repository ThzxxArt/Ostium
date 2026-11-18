# 端口

| 端口 | 协议 | 用途 | 暴露 |
|---|---|---|---|
| 443/tcp | TCP | VLESS Reality / Trojan | 公网 |
| 443/udp | QUIC | Hysteria2 | 公网 |
| 8388/tcp | TCP | Shadowsocks 2022（默认禁用） | 可选 |
| 8000/tcp | HTTP | Django/Gunicorn | 仅回环 |
| 8443/tcp | HTTPS | Caddy 管理面 | 公网（可选） |
| 80/tcp | HTTP | ACME HTTP-01 + 跳转 | 公网（使用 certbot 时） |
| 19090/tcp | HTTP | Clash API | 仅回环 |
| 19091/tcp | gRPC | V2Ray stats | 仅回环 |

防火墙示例（ufw）：

```bash
ufw allow 22/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw allow 8443/tcp   # 使用 Caddy 时
ufw enable
```

不要暴露 8000、19090、19091。

## 端口冲突

- VLESS、Trojan、Shadowsocks 不能共用同一个 TCP 端口。
- Hysteria2 使用 UDP，可与 TCP 443 共用数字端口。
- 配置生成会拒绝冲突；worker 保留旧配置并告警。

## 非 root 绑定

worker 通过 systemd `AmbientCapabilities=CAP_NET_BIND_SERVICE` 绑定 443。
Docker 使用 `cap_add: NET_BIND_SERVICE`。

没有 capability 时，改用高位端口：

```bash
ostium inbound set-port vless 8443
```
