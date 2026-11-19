# CLI

`ostium` 是 Django management command 的薄包装。`--json` 输出机器可读结果；
退出码 `0` 成功、`1` 一般错误、`2` 用法/校验错误。

## 安装与运行

```bash
ostium init --username admin [--domain vpn.example.com]
ostium migrate
ostium collectstatic
ostium web
ostium worker
ostium qcluster
```

## 用户

```bash
ostium user add alice --quota 100G --cycle monthly --expires 2027-01-01T00:00:00Z
ostium user list [--json]
ostium user show alice [--json]
ostium user disable alice
ostium user enable alice
ostium user rotate alice --credentials
ostium user rotate alice --subscription
ostium user reset-usage alice
ostium user subscription alice --reveal
ostium user delete alice
```

## 线路

```bash
ostium inbound init --enable vless,shadowsocks
ostium inbound list
ostium inbound enable hysteria2 --cert vpn.example.com
ostium inbound disable trojan
ostium inbound rotate-keys vless
ostium inbound set-port shadowsocks 8388
```

## 证书

```bash
ostium cert import --domain vpn.example.com --cert fullchain.pem --key privkey.pem
ostium cert sync --dir /etc/letsencrypt/live
ostium cert self-signed --domain test.local --days 365
ostium cert list
ostium cert delete test.local
```

## 备份

```bash
ostium backup create --password '...'
ostium backup list
ostium backup restore /var/lib/ostium/backups/ostium-backup-....ostb --password '...'
```

## 订阅自检

```bash
ostium subscription check --user alice
ostium subscription check --user alice --json
ostium subscription check --user alice --no-binaries
```

自检不会连接代理服务器，只验证生成的订阅结构：

- Clash YAML 不包含 `dns`、`mixed-port`、`GEOIP` 等客户端不友好内容；
- sing-box JSON 不强制 DNS resolver；
- URI / Base64 数量与协议一致；
- 本机存在 `mihomo`、`sing-box`、`xray` 时，额外执行配置校验；不存在则显示
  `SKIP`。

## 诊断

```bash
ostium doctor [--json]
ostium diagnostics export --output /tmp/ostium-diag.tar.gz
ostium status [--json]
ostium apply
```

## API key

```bash
ostium token create ci --scope read --expires 90
ostium token list
ostium token revoke <prefix>
```

## 其他

```bash
ostium changepassword admin       # Django 内置
ostium axes_reset                 # 清除登录锁定
ostium rotate_field_key --new-key '...'
```

`rotate_field_key` 必须离线执行：先停 web/worker/jobs，更新
`/etc/ostium/ostium.env`，再启动。
