# 从 0.1.8 升级到 0.1.9

0.1.9 修复 IPv4-only 服务器上的出站解析：服务端 sing-box 现在强制使用
`ipv4_only` DNS，并通过内部 `local` resolver 解析出站域名。客户端不需要重装。

## 1. 服务器升级

```bash
sudo -u ostium ostium backup create --password 'a long passphrase'
sudo -u ostium ostium status
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/latest/download/install-online.sh \
  | sudo bash -s -- upgrade
```

固定版本：

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/download/v0.1.9/install-online.sh \
  | sudo bash -s -- upgrade --version 0.1.9
```

安装器保留数据库、配置、证书、用户、订阅 token 和 `master.key`。升级后
`ostium-core` 会用新的 DNS 配置重启。

## 2. 客户端

不需要重装客户端。升级服务器后，在 Ostium 里断开再连接一次，或等待 watchdog
重新应用配置，然后测试：

```powershell
curl.exe -I -x http://127.0.0.1:7897 --max-time 20 https://www.google.com
curl.exe -I -x http://127.0.0.1:7897 --max-time 20 https://huggingface.co
```

预期是 TLS 握手成功，而不是 `schannel: failed to receive handshake`。

## 3. 说明

- 0.1.9 默认强制 IPv4 解析。IPv4-only VPS 不应该解析到 AAAA。
- 如果服务器有可用 IPv6，且你明确需要 IPv6 出站，再考虑后续开关；当前默认
  优先保证可用性。
- 出站 IPv6 不需要开放服务器入站端口；入站 IPv6 才需要 IPv6 地址、监听和
  防火墙规则。
- 在线用户是 60 秒流量窗口，不是 TCP 连接状态；断开后最多 60 秒清零。

## 4. 回滚

安装器保留 `venv.old` 和 `pre-upgrade-*` 快照。回滚时停止服务、恢复升级前
快照，再安装 0.1.8 wheel。不要删除 `master.key`。
