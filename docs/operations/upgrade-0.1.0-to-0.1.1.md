# 从 0.1.0 升级到 0.1.1

0.1.1 是安全与正确性补丁，不新增协议族。升级前请先备份。

## 1. 升级前检查

```bash
sudo -u ostium ostium backup create --password 'a long passphrase'
sudo -u ostium ostium version
sudo ss -lntp | grep 8443
```

确认 8443 没有对公网放行。升级期间控制面会短暂停止；核心尽量保持运行。

## 2. 升级

推荐一键升级：

```bash
sudo bash install-online.sh upgrade --version 0.1.1
```

或使用原生包/离线包。升级完成后检查：

```bash
curl -fsS http://127.0.0.1:8443/healthz
curl -fsS http://127.0.0.1:8443/readyz
```

## 3. 默认管理面迁移

0.1.0 的服务端配置通常是：

```toml
host = "0.0.0.0"
public_ui = false
```

0.1.1 首次启动会把这种配置收敛为：

```toml
host = "127.0.0.1"
allow_insecure_bind = false
```

远程管理请使用：

```bash
ssh -L 8443:127.0.0.1:8443 user@server
```

如果确实需要在可信网络中保留明文监听，显式设置：

```toml
host = "0.0.0.0"
allow_insecure_bind = true
```

并只允许已知 CIDR 访问 8443。更好的做法是启用 Public UI（TLS + TOTP）或在前面放 Nginx TLS。

## 4. 订阅与 SS2022

已有 SS2022 用户的订阅需要重新生成/重新导入：0.1.1 的客户端密码改为
`server_key:user_key`。旧订阅只包含 user key，无法连接。其他协议无需变更。

订阅 URL 现在使用 `public_base_url` 或 `--domain` 派生地址。若从 SSH 隧道访问，
请在 Settings 中确认 `public_base_url` 是客户端可访问的 HTTPS 地址。

## 5. 证书与线路

0.1.1 不再自动把“任意 ready 证书”套到 Hysteria2/Trojan。升级后打开“线路”页，
为每个 TLS inbound 选择证书；否则该 inbound 会被跳过并显示原因。已有
`certificate_id` 绑定会保留。续期失败不会中断现有 TLS。

## 6. TOTP 与备份

- 未确认的 TOTP 设置现在不会激活；如果 0.1.0 中打开过设置弹窗但未确认，
  升级后不会要求 TOTP。
- 明文备份包含 `master.key`；API/UI 现在需要显式确认。自动备份默认关闭，
  开启后每天一次、保留 7 份、权限 0600。

## 7. 回滚

1. 停止 `ostium.service`（核心可继续运行）。
2. 重新安装 0.1.0 wheel 或使用升级器保留的 `venv.old`。
3. 如果数据库迁移不兼容，从升级前备份恢复。
4. 启动并检查 `/healthz`、`/readyz`、登录、订阅与核心状态。

0.1.1 的 schema 与 0.1.0 相同（新设置写入 `settings` 表），正常情况下可直接回滚
应用版本；仍建议保留数据库备份。
