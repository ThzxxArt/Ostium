# 订阅格式参考

## Base64

```text
vless://...
hysteria2://...
trojan://...
ss://...
```

整体 Base64，每行一条 URI，末尾换行。

## URI

### VLESS Reality

```text
vless://<uuid>@<host>:<port>?encryption=none&security=reality&sni=<sni>&fp=chrome&pbk=<pbk>&sid=<sid>&type=tcp&flow=xtls-rprx-vision#<name>
```

### Hysteria2

```text
hysteria2://<password>@<host>:<port>?sni=<sni>&insecure=0[&obfs=salamander&obfs-password=<pwd>]#<name>
```

自签证书追加 `pinSHA256=<hex>`（完整证书 DER 的 SHA-256）。

### Trojan

```text
trojan://<password>@<host>:<port>?security=tls&sni=<sni>&type=tcp&allowInsecure=0[&pcs=<base64>]#<name>
```

自签证书追加 `pcs=<base64(SHA256(certificate DER))>`。

### Shadowsocks 2022

```text
ss://<method>:<percent-encoded(server_key:user_key)>@<host>:<port>#<name>
```

SIP022 规定 2022 方法的 userinfo 不使用 Base64；方法名与
`server_key:user_key` 按 RFC 3986 百分号编码（`:` → `%3A`、`=` → `%3D`、
`/` → `%2F`、`+` → `%2B`）。经典 Shadowsocks 仍使用 URL-safe Base64。

## Clash

- `mixed-port: 7890`
- fake-IP DNS
- `Ostium` select / `Auto` url-test
- 私有地址直连、`GEOIP,CN,DIRECT`、`MATCH,Ostium`

## sing-box

- mixed 入站 `127.0.0.1:7890`
- Reality / Hysteria2 / Trojan / Shadowsocks 出站
- 自签 Hysteria2/Trojan 使用 `tls.certificate_public_key_sha256`（SPKI pin）
- `Auto` urltest、`Ostium` selector
- 不启用 TUN

## Content-Type

| target | Content-Type |
|---|---|
| base64/uri | `text/plain; charset=utf-8` |
| clash | `text/yaml; charset=utf-8` |
| singbox | `application/json; charset=utf-8` |
