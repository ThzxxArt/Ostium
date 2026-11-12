# 服务管理

Ostium 不绑定某一种 init 系统。默认安装器在 Linux 使用 systemd、macOS 使用 launchd、Windows 使用 SCM；Docker 使用容器入口。其他环境可以用 `--no-service`，交给任意进程管理器。

## 支持矩阵

| 平台 / 管理器 | 默认支持 | 说明 |
|---|---|---|
| Linux systemd | ✅ | 默认；两个 unit + root drop-in 可选 |
| macOS launchd | ✅ | 核心 LaunchDaemon；UI LaunchAgent 或 root LaunchDaemon |
| Windows SCM | ✅ | `OstiumCore` 服务 + 登录任务或 SYSTEM 任务 |
| Docker | ✅ | `deploy/docker/entrypoint.sh` 前台运行两个进程 |
| OpenRC | ✅（`--no-service`） | 提供示例脚本 |
| runit | ✅（`--no-service`） | 提供示例脚本 |
| s6 / s6-rc | ✅（`--no-service`） | 提供示例脚本 |
| supervisord | ✅（`--no-service`） | 提供示例配置 |
| 手动 / tmux | ✅（`--no-service`） | 适合调试，不建议长期生产 |

## systemd（默认）

安装：

```bash
curl -fsSL .../install-online.sh | sudo bash -s -- install --role server --domain vpn.example.com
```

管理：

```bash
systemctl status ostium-core ostium
journalctl -u ostium -u ostium-core -f
sudo systemctl restart ostium-core ostium
```

服务端默认：

- `ostium.service`：控制面，`User=ostium`
- `ostium-core.service`：核心，`User=ostium` + `CAP_NET_BIND_SERVICE`

客户端默认：

- `ostium-core.service`：核心，`User=ostium-core` + `CAP_NET_ADMIN/CAP_NET_RAW`
- `systemctl --user` 的 `ostium.service`：当前用户 UI

### root 模式

```bash
curl -fsSL .../install-online.sh | sudo bash -s -- install --role server --run-as-root
```

安装器不创建用户，并写入 drop-in：

```ini
# /etc/systemd/system/ostium.service.d/root.conf
[Service]
User=root
Group=root
```

核心同样处理。客户端 root 模式还会把 UI 安装为系统级 `ostium.service`。

查看实际生效配置：

```bash
systemctl cat ostium ostium-core
```

**风险**：root 模式取消控制面与 root 的隔离。Web/API 漏洞、插件漏洞或配置错误都可能直接影响整机。生产环境优先默认模式。

### 自定义用户

默认模式已经使用最小权限用户。若你要替换用户名，可在安装后修改 unit，或直接编辑 drop-in：

```ini
[Service]
User=myuser
Group=mygroup
```

同时确保 `/var/lib/ostium`、`/etc/ostium` 和核心二进制对该用户可读写/可执行。

## OpenRC（Alpine / Gentoo）

先以 `--no-service` 安装：

```bash
sudo bash install-online.sh install --role server --no-service
```

创建 `/etc/init.d/ostium-core`：

```sh
#!/sbin/openrc-run
description="Ostium proxy core"

command="/opt/ostium/venv/bin/ostium"
command_args="core-run"
command_user="ostium:ostium"
directory="/var/lib/ostium"
export OSTIUM_ROLE="server"
export OSTIUM_CONFIG_FILE="/etc/ostium/config.toml"
export OSTIUM_DATA_DIR="/var/lib/ostium"

depend() {
  need net
  after firewall
}
```

创建 `/etc/init.d/ostium`：

```sh
#!/sbin/openrc-run
description="Ostium control plane"

command="/opt/ostium/venv/bin/ostium"
command_args="serve"
command_user="ostium:ostium"
directory="/var/lib/ostium"
export OSTIUM_ROLE="server"
export OSTIUM_CONFIG_FILE="/etc/ostium/config.toml"
export OSTIUM_DATA_DIR="/var/lib/ostium"
export OSTIUM_CONFIG_DIR="/etc/ostium"

depend() {
  need net
  use ostium-core
}
```

```bash
sudo chmod +x /etc/init.d/ostium /etc/init.d/ostium-core
sudo rc-update add ostium-core default
sudo rc-update add ostium default
sudo rc-service ostium-core start
sudo rc-service ostium start
```

## runit

创建 `/etc/sv/ostium-core/run`：

```sh
#!/bin/sh
exec 2>&1
export OSTIUM_ROLE=server
export OSTIUM_CONFIG_FILE=/etc/ostium/config.toml
export OSTIUM_DATA_DIR=/var/lib/ostium
exec chpst -u ostium:ostium /opt/ostium/venv/bin/ostium core-run
```

创建 `/etc/sv/ostium/run`：

```sh
#!/bin/sh
exec 2>&1
export OSTIUM_ROLE=server
export OSTIUM_CONFIG_FILE=/etc/ostium/config.toml
export OSTIUM_DATA_DIR=/var/lib/ostium
export OSTIUM_CONFIG_DIR=/etc/ostium
exec chpst -u ostium:ostium /opt/ostium/venv/bin/ostium serve
```

```bash
chmod +x /etc/sv/ostium-core/run /etc/sv/ostium/run
ln -s /etc/sv/ostium-core /var/service/
ln -s /etc/sv/ostium /var/service/
```

## s6

`/etc/s6/ostium-core/run`：

```sh
#!/bin/execlineb -P
with-contenv
s6-setuidgid ostium
export OSTIUM_ROLE server
export OSTIUM_CONFIG_FILE /etc/ostium/config.toml
export OSTIUM_DATA_DIR /var/lib/ostium
/opt/ostium/venv/bin/ostium core-run
```

`/etc/s6/ostium/run` 同理，把命令换成 `ostium serve`，并加 `OSTIUM_CONFIG_DIR /etc/ostium`。然后用 s6-rc 或你的服务定义把两者加入默认 bundle。

## supervisord

`/etc/supervisor/conf.d/ostium.conf`：

```ini
[program:ostium-core]
command=/opt/ostium/venv/bin/ostium core-run
user=ostium
directory=/var/lib/ostium
environment=OSTIUM_ROLE="server",OSTIUM_CONFIG_FILE="/etc/ostium/config.toml",OSTIUM_DATA_DIR="/var/lib/ostium"
autostart=true
autorestart=true
stopsignal=TERM

[program:ostium]
command=/opt/ostium/venv/bin/ostium serve
user=ostium
directory=/var/lib/ostium
environment=OSTIUM_ROLE="server",OSTIUM_CONFIG_FILE="/etc/ostium/config.toml",OSTIUM_DATA_DIR="/var/lib/ostium",OSTIUM_CONFIG_DIR="/etc/ostium"
autostart=true
autorestart=true
stopsignal=TERM
```

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status
```

## Docker

```bash
docker compose -f deploy/docker/docker-compose.yml up -d
```

容器入口在前台启动 `ostium core-run` 和 `ostium serve`，使用 host 网络绑定 443/80。数据卷：

- `/var/lib/ostium`
- `/etc/ostium`

## 手动运行

```bash
# 终端 1：核心
sudo OSTIUM_ROLE=server OSTIUM_CONFIG_FILE=/etc/ostium/config.toml \
  /opt/ostium/venv/bin/ostium core-run

# 终端 2：控制面
sudo OSTIUM_ROLE=server OSTIUM_CONFIG_FILE=/etc/ostium/config.toml \
  /opt/ostium/venv/bin/ostium serve
```

客户端：

```bash
sudo OSTIUM_ROLE=client OSTIUM_CONFIG_FILE=/etc/ostium/client.toml \
  /opt/ostium/venv/bin/ostium core-run

OSTIUM_ROLE=client OSTIUM_CONFIG_FILE="$HOME/.local/share/ostium/config.toml" \
  OSTIUM_CONFIG_DIR="$HOME/.local/share/ostium" OSTIUM_DATA_DIR="$HOME/.local/share/ostium" \
  OSTIUM_CORE_TOKEN_FILE=/var/lib/ostium-core/runtime/core.token \
  OSTIUM_CORE_URL=http://127.0.0.1:8788 \
  /opt/ostium/venv/bin/ostium serve
```

## 升级与卸载

一键升级：

```bash
sudo bash install-online.sh upgrade
```

no-service 安装也适用；升级只替换 venv/核心，不碰你的 init 脚本。

卸载：

```bash
sudo bash install-online.sh uninstall
# 或彻底删除数据和用户
sudo bash install-online.sh uninstall --purge
```

## 选择建议

- **单机服务器 / 普通 VPS**：systemd 默认模式。
- **容器**：Docker。
- **Alpine / Gentoo / Void**：`--no-service` + OpenRC/runit。
- **单用户测试机，嫌用户权限麻烦**：`--run-as-root`，但要接受隔离降级。
- **已有进程管理器**：`--no-service`，不要同时注册 systemd，避免两个实例抢端口。
