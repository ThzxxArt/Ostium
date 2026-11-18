# 证书

Hysteria2 与 Trojan 需要 TLS 证书。Ostium 不内置 ACME；证书由 certbot 或你手动提供。

## 手动导入

控制台「证书 → 导入」，或：

```bash
ostium cert import \
  --domain vpn.example.com \
  --cert /path/fullchain.pem \
  --key /path/privkey.pem
```

导入时会校验：

- PEM 格式；
- 私钥与证书公钥匹配；
- 证书 SAN/CN 覆盖域名；
- 证书未过期；
- 文件写入 `certs/<domain>/`，权限 0600。

## certbot

安装器（`--with-caddy`）会申请证书并安装 deploy hook。
手动配置：

```bash
certbot certonly --webroot -w /var/www/certbot -d vpn.example.com

cat >/etc/letsencrypt/renewal-hooks/deploy/ostium.sh <<'EOF'
#!/bin/sh
runuser -u ostium -- /usr/local/bin/ostium cert sync --dir /etc/letsencrypt/live
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/ostium.sh
```

`cert sync` 会递归查找 `fullchain.pem` + `privkey.pem`，导入并触发配置更新。

## 自签证书

```bash
ostium cert self-signed --domain test.local --days 365
```

自签证书适合内网测试。订阅会尽量包含 `pinSHA256`，但不同客户端支持不一致；
生产环境请使用可信证书。

## 到期

- ≤30 天：总览与证书页告警。
- 过期：配置生成失败，worker 保留旧配置。
- 证书被线路使用时不能删除。

## 校验

```bash
ostium cert list
ostium doctor
```
