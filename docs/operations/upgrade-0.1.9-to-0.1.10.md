# 从 0.1.9 升级到 0.1.10

0.1.10 修复服务端 DNS 解析：不再使用会被污染的 `223.5.5.5`，改用
`8.8.8.8` / `1.1.1.1`，并保留 `ipv4_only`。客户端不需要重装。

## 1. 服务器升级

```bash
sudo -u ostium ostium backup create --password 'a long passphrase'
sudo -u ostium ostium status
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/latest/download/install-online.sh \
  | sudo bash -s -- upgrade
```

固定版本：

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/download/v0.1.10/install-online.sh \
  | sudo bash -s -- upgrade --version 0.1.10
```

升级后确认服务器版本和新的 DNS：

```bash
ostium version
curl -fsS https://ostium.thzxxart.com:8443/healthz
sudo python3 -c 'import json; d=json.load(open("/var/lib/ostium/runtime/last-good.json")); print(d["dns"])'
```

预期：

```text
Ostium 0.1.10
{"status":"ok","version":"0.1.10"}
DNS 包含 8.8.8.8 和 1.1.1.1，不再包含 223.5.5.5
```

## 2. 客户端

不需要重装。服务器升级完成后在 Ostium 里断开再连接一次，然后测试：

```powershell
curl.exe -I -x http://127.0.0.1:7897 --max-time 20 https://www.google.com
curl.exe -I -x http://127.0.0.1:7897 --max-time 20 https://huggingface.co
```

预期 TLS 握手成功。

如果客户端页面仍显示旧版本，先确认 `ostium version` 和
`Get-Process ostium` 的路径；旧 UI 进程需要重启，安装包未替换时重新安装。

## 3. 说明

- `223.5.5.5` 在部署环境中把 Google/Hugging Face 解析成错误 IP，TCP 能连但
  TLS 失败；GitHub 恰好解析正确。
- 服务器没有 IPv6 地址/默认路由，出站 IPv6 不需要开放入站端口。
- 在线用户是 60 秒流量窗口；断开后最多 60 秒清零。

## 4. 回滚

安装器保留 `venv.old` 和 `pre-upgrade-*` 快照。回滚时停止服务、恢复升级前
快照，再安装 0.1.9 wheel。不要删除 `master.key`。
