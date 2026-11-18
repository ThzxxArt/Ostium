# 协议与线路

Ostium 固定四条线路，每条线路对应一个 `Inbound` 记录。

## VLESS Reality

- 默认端口 443/tcp，默认启用。
- 使用 X25519 密钥对、short_id、SNI 与 TLS 1.3 Reality 握手。
- 客户端 flow：`xtls-rprx-vision`。
- 不需要证书；轮换 Reality 密钥会立即使旧订阅失效。

## Hysteria2

- 默认 443/udp。
- 基于 QUIC，适合高延迟/丢包网络。
- 必须分配可用 TLS 证书。
- 可启用 salamander 混淆；密钥随线路保存。

## Trojan

- 默认 443/tcp。
- TLS 伪装，兼容性广。
- 必须分配可用 TLS 证书。

## Shadowsocks 2022

- 默认 8388/tcp。
- 仅支持 `2022-blake3-*` 方法。
- 服务端持有 server key，每个用户有独立 user key。
- 客户端密码格式：`server_key:user_key`。

## 端口规则

- VLESS、Trojan、Shadowsocks 共享 TCP 端口空间，不能冲突。
- Hysteria2 使用 UDP，可与 TCP 443 共用端口号。
- 保存后 worker 生成配置；端口冲突会导致 apply 失败并保留旧配置。

## 启用线路

控制台「线路」页，或：

```bash
ostium inbound enable vless
ostium inbound enable hysteria2 --cert vpn.example.com
ostium inbound rotate-keys vless
ostium inbound set-port shadowsocks 8388
```

每次变更都会递增 `desired_revision`，worker 在 1 秒内检测并应用。
