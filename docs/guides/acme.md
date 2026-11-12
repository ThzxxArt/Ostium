# ACME 指南

Ostium 内置 Let's Encrypt ACME HTTP-01 客户端，用于 Hysteria2、Trojan 和公网管理 UI。

## 前提

- 域名 A/AAAA 记录指向本机。
- 签发期间公网能访问 TCP 80。
- UI 服务能绑定 80（服务端默认有 `CAP_NET_BIND_SERVICE`）。

## 签发

1. 打开 **Certificates → Issue**。
2. 输入域名，选择 **ACME HTTP-01**。
3. 默认使用生产目录；测试时勾选 **staging**。
4. 在 **Jobs** 查看进度。挑战服务器只在订单期间绑定 80，并且只提供一个 key authorization。
5. 成功后证书保存到 `/var/lib/ostium/certs/<domain>/fullchain.pem` 和 `privkey.pem`（0600），并自动分配给 Hysteria2/Trojan。

## 续期

Ostium 每天检查一次，剩余不足 30 天时自动续期。续期失败会产生告警，并保留旧证书。

UI 和核心是两个服务，所以 UI TLS 变更后需要重启 `ostium.service`；隧道不会中断。

## 手动上传与自签

- **Upload** 会校验 PEM 解析、私钥匹配、域名覆盖和有效期，然后写文件。
- **Self-signed** 适合 Hysteria2 pinning/本地测试。公网 UI 不建议使用自签证书，客户端必须信任或 pin。

## 边界

v0.1.0 只支持 HTTP-01。DNS-01 和 TLS-ALPN-01 明确不在范围内（不接 DNS 服务商 API，也避免与 443 的 Reality 监听冲突）。

## 常见错误

- 80 端口被 nginx/caddy 占用：临时停掉，或让 ACME 使用其他方式（v0.1.0 不支持）。
- 域名解析未生效：用 `dig`/`nslookup` 确认 A/AAAA。
- 云安全组未放行 80：同时检查本机防火墙和云防火墙。
- 证书域名不匹配：确认申请域名和实际访问域名一致。
