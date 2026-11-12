# 一键安装（推荐）

Ostium 提供**在线一键安装器**：不需要预装 Python，也不需要先配置 venv。脚本会自动下载静态 uv、托管 Python 3.13、程序 wheel、sing-box 核心，校验 SHA256，并注册系统服务。

> 适用：Ubuntu 24.04 / Debian 13 服务器，Windows 10 22H2+ / 11，macOS 14+ 客户端。

## Linux 服务端

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/scripts/install-online.sh \
  | sudo bash -s -- install --role server --domain vpn.example.com
```

安装完成后：

```bash
ssh -L 8443:127.0.0.1:8443 root@your-server
```

打开 <http://127.0.0.1:8443>，用安装器打印的密码登录，立即启用 TOTP。

## Linux 客户端

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/scripts/install-online.sh \
  | sudo bash -s -- install --role client
```

然后打开 <http://127.0.0.1:8787>，完成向导并导入订阅。

## macOS 客户端

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/scripts/install-online.sh \
  | sudo bash -s -- install --role client
```

macOS 只支持客户端；服务端请用 Linux。

## Windows 客户端

以**管理员 PowerShell**运行：

```powershell
irm https://raw.githubusercontent.com/ThzxxArt/Ostium/main/scripts/install-online.ps1 | iex
```

脚本会下载并静默运行 Windows 安装包、校验 SHA256，然后打印初始管理员密码。默认：

- `OstiumCore` 服务以 LocalSystem 运行 TUN 核心；
- Web UI 在当前用户登录时启动；
- 数据在 `%ProgramData%\Ostium`。

需要连 UI 也以 SYSTEM 运行时：

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/ThzxxArt/Ostium/main/scripts/install-online.ps1))) -RunAsSystem
```

## 安装器做了什么

1. 检测 Linux/macOS、x86_64/arm64。
2. 缺 `curl`/`tar` 时用 apt/dnf/yum 安装最小依赖。
3. 下载静态 `uv` 到 `/opt/ostium/uv`。
4. 用 `uv` 安装托管 Python 3.13 到 `/opt/ostium/python`，**不碰系统 Python**。
5. 从 GitHub Release 下载：
   - `ostium_ctl-<version>-py3-none-any.whl`
   - `ostium-core-1.14.4-ostium.1-<os>-<arch>.tar.gz`
   - `SHA256SUMS`
6. 校验通过后调用仓库内的 `scripts/install.sh` 或 `deploy/launchd/install-macos.sh`。
7. 服务端创建服务用户、安装核心、初始化数据库、注册 systemd/launchd 并启动，打印一次性管理员密码。
8. 客户端不预置管理员密码；首次打开 UI 时完成客户端设置向导。

## 常用参数

| 参数 | 说明 |
|---|---|
| `--role server\|client` | 角色；默认 server |
| `--domain vpn.example.com` | 服务端域名（Reality 可省略） |
| `--version 0.1.0` | 指定 Release 版本；`latest` 自动解析 |
| `--password '...'` | 初始管理员密码；省略则随机生成 |
| `--prefix /opt/ostium` | 安装目录 |
| `--run-as-root` | 不创建用户，两个服务都用 root 运行 |
| `--no-service` | 不注册 systemd/launchd，交给自己的进程管理器 |
| `--behind-proxy` | Nginx/Caddy 反代：UI 只监听 127.0.0.1，启用 Secure Cookie |
| `--ui-host HOST` | 管理 UI 监听地址（默认 0.0.0.0） |
| `--ui-port PORT` | 管理 UI 端口（默认 8443） |
| `--public-ui` | 允许公网管理 UI（必须先 TLS + TOTP） |
| `--no-start` | 注册服务但不启动 |
| `--local-dir DIR` | 离线安装：Release 目录或源码 checkout |
| `--no-verify` | 跳过 SHA256（仅限本地开发） |

## 没有 Python 也能装

一键脚本的第一阶段只依赖 `curl`/`wget` 和 `tar`。Python 由 uv 下载并放在安装目录里，不写入 `/usr/bin`，也不会与系统包管理器冲突。升级时同样复用托管 Python。

如果你连 `curl` 都没有，脚本会在 Debian/Ubuntu 上用 `apt-get` 安装 `curl`、`ca-certificates`、`tar`；RHEL 系用 `dnf`/`yum`。Alpine 等非 systemd 系统请用 `--no-service`，并自行提供 `curl`/`tar`。

## Nginx / Caddy 反代模式

Nginx 已占用 80/443 时：

```bash
curl -fsSL .../install-online.sh | sudo bash -s -- install --role server \
  --domain admin.example.com --behind-proxy
```

它会：

- 把 Ostium UI 绑定到 `127.0.0.1:8443`；
- 设置 `secure_cookies = true`；
- 把 `admin.example.com` 加入 `trusted_hosts`。

然后按 [Nginx 共存指南](nginx.md) 配置证书和反代，并把 Reality/Trojan 改到 9443/tcp。`--behind-proxy` 只影响管理 UI，不会改变代理入口端口。

## root 模式（不创建 ostium 用户）

```bash
curl -fsSL .../install-online.sh | sudo bash -s -- install --role server --run-as-root
```

行为：

- 不创建 `ostium` / `ostium-core` 用户；
- 控制面和核心都以 root 运行；
- systemd 通过 drop-in 覆盖 `User=root` / `Group=root`；
- 客户端 UI 也会安装为系统服务 `ostium.service`。

**风险**：默认模式把控制面和 root 隔开，Web/API 漏洞不能直接拿 root。`--run-as-root` 取消这层隔离，只建议单用户测试机、临时环境，或你已经用容器/虚拟机隔离了风险。生产环境优先默认模式。

## 不用 systemd：no-service 模式

```bash
curl -fsSL .../install-online.sh | sudo bash -s -- install --role server --no-service
```

安装器只安装文件、核心和配置，不写 unit。你可以用 OpenRC、runit、s6、supervisord 或手动运行：

```bash
sudo OSTIUM_ROLE=server OSTIUM_CONFIG_FILE=/etc/ostium/config.toml \
  /opt/ostium/venv/bin/ostium core-run

sudo OSTIUM_ROLE=server OSTIUM_CONFIG_FILE=/etc/ostium/config.toml \
  /opt/ostium/venv/bin/ostium serve
```

完整示例见 [服务管理](service-manager.md)。

## 离线 / 内网安装

准备一个目录，包含：

```text
release/
├── ostium_ctl-0.1.0-py3-none-any.whl
├── ostium-core-1.14.4-ostium.1-linux-amd64.tar.gz
├── SHA256SUMS
├── scripts/install.sh
└── deploy/...
```

然后：

```bash
sudo bash install-online.sh install \
  --local-dir /path/to/release \
  --role server --domain vpn.example.com
```

`--local-dir` 也可以直接指向源码 checkout；脚本会从 `dist/` 或目录内查找 wheel 和核心包。没有 `SHA256SUMS` 时可用 `--no-verify`，但生产环境不建议。

## 升级

```bash
sudo bash install-online.sh upgrade
```

升级会：

- 停止控制面（核心尽量保持运行）；
- 替换 venv 和核心二进制；
- 保留数据库、`master.key`、配置、证书和用户；
- 重新启动服务。

如果原来是 root 模式，脚本会自动检测 drop-in 并保持 root 模式。

指定版本：

```bash
sudo bash install-online.sh upgrade --version 0.1.1
```

## 卸载

```bash
sudo bash install-online.sh uninstall
```

默认保留数据与配置。彻底删除：

```bash
sudo bash install-online.sh uninstall --purge
```

## 状态

```bash
sudo bash install-online.sh status
```

## 故障排查

| 现象 | 处理 |
|---|---|
| `curl: command not found` | 先安装 curl，或用 `wget` 下载脚本后执行 |
| GitHub 下载失败 | 配置代理/镜像，或用 `--local-dir` 离线安装 |
| SHA256 不匹配 | 不要继续；重新下载，检查镜像或代理是否篡改 |
| 443 被占用 | `ss -lntup \| grep :443`，停掉冲突的 nginx/caddy |
| 服务未启动 | `systemctl status ostium-core ostium`；`journalctl -u ostium -u ostium-core -f` |
| 没有 systemd | 安装时加 `--no-service`，按[服务管理](service-manager.md)配置 |
| 忘记管理员密码 | 没有后门；用备份恢复，或在确认数据可丢弃时重装 |

## 安全建议

- 默认安装已经比 root 模式安全；除非明确需要，不要加 `--run-as-root`。
- 管理 UI 默认只监听回环；公网访问必须先配 TLS + TOTP。
- 只放行 22、80、443/tcp、443/udp；不要默认放行 8388/8443。
- 定期把加密备份存到异地；备份包含 `master.key`。
