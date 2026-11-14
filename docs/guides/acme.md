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
5. 成功后证书保存到 `/var/lib/ostium/certs/<domain>/fullchain.pem` 和 `privkey.pem`（0600），并只自动分配给尚未绑定证书的 Hysteria2/Trojan；已有显式绑定不会被覆盖。

## 续期

Ostium 每 6 小时检查一次，剩余不足 30 天时自动续期。续期失败会记录日志并创建
`certificate_renewal_failed` 告警，同时保留旧证书；证书进入 14 天窗口后还会生成到期告警。

签发任务支持 per-issue `staging` 与 `email` 覆盖；全局 ACME 邮箱/staging 在 Settings 中配置。
证书必须在线路页绑定到具体 inbound，不存在“任意 ready 证书兜底”。

UI 和核心是两个服务，所以 UI TLS 变更后需要重启 `ostium.service`；隧道不会中断。

## 手动上传与自签

- **Upload** 会校验 PEM 解析、私钥匹配、域名覆盖和有效期，然后写文件。
- **Self-signed** 适合 Hysteria2 pinning/本地测试。公网 UI 不建议使用自签证书，客户端必须信任或 pin。

## 边界

当前版本只支持 HTTP-01。DNS-01 和 TLS-ALPN-01 明确不在范围内（不接 DNS 服务商 API，也避免与 443 的 Reality 监听冲突）。

## 账户密钥轮换

ACME 账户私钥加密保存在数据目录 `acme/account.key.enc`。轮换步骤：

1. 备份数据目录；
2. 停止 `ostium.service`；
3. 删除 `acme/account.key.enc`（下次签发会生成新账户密钥并重新注册）；
4. 启动服务并签发一次 staging 证书验证账户可用；
5. 再执行生产签发。

轮换账户密钥不会使已签发证书失效，但旧账户将无法再用于续期。

## 常见错误

- 80 端口被 nginx/caddy 占用：临时停掉，或让 ACME 使用其他方式（当前版本不支持）。
- 域名解析未生效：用 `dig`/`nslookup` 确认 A/AAAA。
- 云安全组未放行 80：同时检查本机防火墙和云防火墙。
- 证书域名不匹配：确认申请域名和实际访问域名一致。
