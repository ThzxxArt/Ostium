# Ostium Profile v1

原生订阅格式是一份确定性的 JSON：

```json
{
  "format": "ostium-profile",
  "version": 1,
  "name": "alice",
  "generated_at": "2026-11-12T00:00:00+00:00",
  "endpoints": [
    {
      "tag": "alice-reality",
      "protocol": "vless-reality",
      "name": "HK · Reality",
      "server": "vpn.example.com",
      "port": 443,
      "uuid": "2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
      "flow": "xtls-rprx-vision",
      "tls": {
        "enabled": true,
        "server_name": "www.apple.com",
        "insecure": false,
        "fingerprint": "chrome",
        "reality_public_key": "…",
        "reality_short_id": "…"
      }
    }
  ],
  "routing_mode": "smart",
  "metadata": {"user": "alice", "source": "ostium"}
}
```

支持协议：`vless-reality`、`hysteria2`、`trojan`、`shadowsocks`。未知字段会被 Pydantic 模型拒绝。也支持 URI 导入：

- `vless://UUID@host:443?...`
- `hysteria2://password@host:443?...`
- `trojan://password@host:443?...`
- `ss://base64(method:password)@host:8388#name`

导出永远不会包含订阅 token、管理员会话或私钥。
