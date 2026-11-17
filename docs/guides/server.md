# 服务端指南（Ubuntu 24.04 / Debian 13）

## 基础要求

- 1 vCPU / 1 GB 可运行；推荐 2 vCPU / 2 GB。
- 20 GB SSD、IPv4/IPv6、UTC 时区、NTP 同步。
- 放行 22（限制来源）、80/tcp（ACME）、443/tcp、443/udp。
- 只有明确要公网管理 UI 时才放行 8443。

> 默认安装会创建无特权 `ostium` 用户。若使用 `--run-as-root`，控制面也会以 root 运行，隔离降级；详见[服务管理](service-manager.md)。

## 一键安装（推荐）

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/latest/download/install-online.sh \
  | sudo bash -s -- install --role server --domain vpn.example.com
```

脚本会自动下载 uv、托管 Python 3.13、wheel、sing-box 核心和校验文件，然后注册 systemd。无需预装 Python。

安装完成后用 SSH 隧道访问：

```bash
ssh -L 8443:127.0.0.1:8443 root@your-server
```

打开 <http://127.0.0.1:8443>。Reality 默认启用；创建用户后把订阅导入客户端。

## 离线安装

从 GitHub Release 下载：

- `ostium_ctl-0.1.10-py3-none-any.whl`
- `ostium-core-1.14.4-ostium.1-linux-amd64.tar.gz`（arm64 选对应架构）
- `SHA256SUMS`
- 源码包或包含 `scripts/`、`deploy/` 的目录

```bash
sha256sum -c SHA256SUMS --ignore-missing
sudo ./install.sh --role server \
  --wheel ./ostium_ctl-0.1.10-py3-none-any.whl \
  --core ./ostium-core-1.14.4-ostium.1-linux-amd64.tar.gz \
  --domain vpn.example.com
```

也可以使用一键脚本的离线模式：

```bash
sudo bash install-online.sh install --local-dir /path/to/release --role server --domain vpn.example.com
```

## root 模式

```bash
curl -fsSL .../install-online.sh | sudo bash -s -- install --role server --run-as-root
```

不创建 `ostium` 用户，两个 systemd 服务都以 root 运行。方便，但**不推荐生产环境**：Web/API 漏洞将直接影响整机。安装器会写 drop-in，升级时自动保持该模式。

## 不用 systemd

```bash
curl -fsSL .../install-online.sh | sudo bash -s -- install --role server --no-service
```

然后按[服务管理](service-manager.md)配置 OpenRC、runit、s6 或 supervisord。

## 防火墙

```bash
ufw default deny incoming
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw enable
```

同时配置云安全组。除非明确启用 Shadowsocks 2022，不要暴露 8388。

## sysctl

```ini
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
fs.file-max = 1000000
```

```bash
sudo sysctl --system
```

核心 unit 已设置 `LimitNOFILE=65535`。

## 服务管理

```bash
systemctl status ostium-core ostium
journalctl -u ostium -u ostium-core -f
```

UI 可以重启/重载核心，但不能重启自己。修改监听地址或 TLS 后：

```bash
sudo systemctl restart ostium
```

## TLS 与公网 UI

1. 在 **Certificates** 申请 ACME HTTP-01 证书，或上传证书。
2. 把证书分配给 Hysteria2 / Trojan。
3. 启用 TOTP。
4. 在 Settings 打开 **Public admin UI**。
5. 重启 `ostium.service`。

UI 默认只监听回环；非回环明文监听需要显式 `allow_insecure_bind`，否则 `ostium serve` 直接拒绝启动。Public UI 仍需 TLS + TOTP。当前版本只支持 HTTP-01。

在 Settings 开启 Public UI 时，如果当前监听地址仍是回环，Ostium 会自动改为 `0.0.0.0` 并在关闭时恢复 `127.0.0.1`；自定义监听地址不会被覆盖。默认端口是 8443，因此健康检查是 `https://域名:8443/healthz`；只有显式把服务监听改成 443 时才省略端口。重启后请先从本机确认健康检查，再关闭 SSH 隧道。

## 分流规则

服务端 **Routing** 页会把规则保存在本地数据库，但当前版本不会把自定义规则通过订阅分发给客户端；客户端会在应用的
Routing 页使用同一套规则编辑器，并立即应用到自己的核心。需要统一分流时，请在每个客户端导入/配置对应规则。

## 备份

在 Settings 创建加密备份，或：

```bash
sudo -u ostium ostium backup create --password 'a long passphrase'
```

文件在 `/var/lib/ostium/backups`。请存到异地。恢复需要停止两个服务，或从 UI staging 后重启。

root 模式下把 `sudo -u ostium` 换成 `sudo`。

## 日常运维

服务端配置默认是 `0600 ostium:ostium`；普通 sudo 用户直接运行会读不到配置。使用服务用户执行：

```bash
sudo -u ostium ostium doctor
sudo -u ostium ostium logs --source core -f
sudo -u ostium ostium diagnostics export
sudo -u ostium ostium core version
sudo ostium update --check
```

root 部署（`--run-as-root`）去掉 `sudo -u ostium`。

## 服务端 DNS（0.1.11）

服务端默认 `server_dns_mode = "auto"`：

- 启动时通过 DoH 查询一个已知域名；成功则生成一个 `https` DNS 服务器。
- 探测失败时回退到 UDP `8.8.8.8`，并写入 warning 日志和告警。
- 配置为 `doh` 时故障会拒绝启动，避免静默降级；配置为 `udp` 时不做探测。

```toml
server_dns_mode = "auto"          # auto | doh | udp
server_dns_doh_url = "https://1.1.1.1/dns-query"
```

`last-good.meta.json` 记录 `policy_version: 3`、实际 `dns_mode`、`dns_servers`、
探测时间和配置 SHA256。旧策略版本的核心会等待控制面重新 apply，不会继续运行。

## 安全底线

- 默认不要用 root 跑控制面；如使用 `--run-as-root`，明确接受风险。
- 没有 TLS + TOTP 不要把管理 UI 暴露公网。
- 只开放必要端口。
- 定期备份，并把备份视为最高敏感文件。
