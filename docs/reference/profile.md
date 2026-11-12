# Ostium Profile v1

The native subscription format is a deterministic JSON document:

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

Supported protocols: `vless-reality`, `hysteria2`, `trojan`, `shadowsocks`.
Unknown fields are rejected by the Pydantic model. URIs are also accepted for
import:

- `vless://UUID@host:443?...`
- `hysteria2://password@host:443?...`
- `trojan://password@host:443?...`
- `ss://base64(method:password)@host:8388#name`

Exports never include the subscription token, admin session or private keys.
