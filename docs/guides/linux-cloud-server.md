# Linux 云服务器部署 Ostium 服务端

本文面向一台全新的 Linux 云服务器，域名的 A/AAAA 记录已经指向服务器，TLS 证书已经取得。目标是把 Ostium 服务端部署起来，完成管理 UI、代理入口、用户订阅和客户端连接。

本文以常见 systemd 发行版为主：

- Debian / Ubuntu（apt、ufw）
- RHEL / Rocky Linux / AlmaLinux（dnf、firewalld）
- Alpine / OpenRC 等非 systemd 发行版使用 `--no-service` + supervisord，见第 4.4 节

> **兼容性说明**：Ostium 0.1.1 的发布验证矩阵是 Ubuntu 24.04 / Debian 13，其他发行版没有实机验证。优先使用在线安装器（wheel + 托管 Python）；Release 里的 PyInstaller DEB/AppImage 依赖构建环境，较旧发行版可能遇到 glibc 不兼容，不建议作为通用安装方式。

## 1. 主方案与端口规划

本文**不把 Nginx 作为默认方案**。主方案由 Ostium 自己终止 TLS：

- 管理 UI 使用 Ostium 的 Public UI；
- 证书直接上传到 Ostium；
- 不安装 Nginx；
- 只有已经运行 Nginx，或需要同机托管其他网站时，才看文末的 Nginx 附录。

### 1.1 推荐主方案：Public UI 8443

| 用途 | 端口 |
|---|---|
| SSH | 22/tcp |
| HTTP（证书续期/ACME） | 80/tcp |
| Reality | 443/tcp |
| Hysteria2（可选） | 443/udp |
| Ostium 管理 UI | 8443/tcp |
| Trojan（可选） | 9443/tcp |

特点：

- Reality 保持默认 443/tcp；
- UI 使用 `https://域名:8443`；
- 不需要 Nginx；
- 首次登录仍建议走 SSH 隧道，因为默认 UI 只监听回环。

### 1.2 需要标准 443：Public UI 443

| 用途 | 端口 |
|---|---|
| SSH | 22/tcp |
| HTTP | 80/tcp |
| Ostium 管理 UI | 443/tcp |
| Reality | 9443/tcp |
| Hysteria2（可选） | 443/udp |
| Trojan（可选） | 9444/tcp |

特点：

- UI 使用 `https://域名`，不带端口；
- 必须先把 Reality 从 443/tcp 移到 9443/tcp；
- 仍然不需要 Nginx。

### 1.3 Nginx 可选方案

只有以下情况才用 Nginx：

- 服务器上已经有 Nginx，且 80/443 已经被其他站点占用；
- 需要同一台机器托管多个 HTTPS 网站；
- 希望由 Nginx/certbot 统一管理证书。

Nginx 方案见本文附录，不作为主路径。

## 2. 首次能用公网 IP 打开网页吗？

**默认不能。**

Ostium 0.1.1 默认把管理 UI 绑定在 `127.0.0.1:8443`，只允许本机访问。这是安全设计，不是安装失败。默认安装后：

- `http://公网IP:8443` 连接不上；
- `https://公网IP:8443` 也连接不上；
- 必须在你自己的电脑上建立到服务器的 SSH 隧道，再从本地浏览器访问 `http://127.0.0.1:8443`。

推荐首次登录方式：

```bash
ssh -N -L 8443:127.0.0.1:8443 root@SERVER_IP
```

然后在本机浏览器打开：

```text
http://127.0.0.1:8443
```

完整的逐步操作、Windows/PuTTY 写法和隧道排错见第 5 节。

### 2.1 为什么不能直接用公网 IP

即使把 UI 改成监听 `0.0.0.0`，Ostium 还会校验 HTTP `Host` 头。公网 IP 字面量默认不在 `trusted_hosts` 中，会返回：

```text
400 invalid Host header
```

这是为了防止 DNS rebinding。要强行用公网 IP 打开，需要同时：

1. 安装时加 `--ui-host 0.0.0.0 --allow-insecure-bind`；
2. 把公网 IP 加入 `trusted_hosts`；
3. 在防火墙中限制 8443 只允许自己的来源 IP。

这会暴露**明文 HTTP 管理界面**，不建议用于生产。正确做法是先用 SSH 隧道完成首次设置，再启用 TLS 域名访问。

### 2.2 启用 Public UI 之后

启用 Public UI 后，Ostium 会监听 `0.0.0.0`，但访问地址应该是域名：

```text
https://vpn.example.com:8443
```

不要使用：

```text
https://公网IP:8443
```

因为证书是签给域名的，用 IP 访问会证书不匹配。除非证书本身包含 IP SAN（Let's Encrypt 通常不签发 IP 证书），否则浏览器会报错。

如果使用标准 443 变体，访问地址是：

```text
https://vpn.example.com
```

公网 IP 仍然只建议用于客户端连接代理入口，不建议作为管理 UI 地址。

### 2.3 如果只是临时验证公网 IP

仅在隔离测试环境、且明确接受风险时，可以临时这样做：

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/download/v0.1.1/install-online.sh \
  | sudo bash -s -- install \
      --role server \
      --domain vpn.example.com \
      --version 0.1.1 \
      --ui-host 0.0.0.0 \
      --allow-insecure-bind
```

然后编辑 `/etc/ostium/config.toml`，把公网 IP 加入 `trusted_hosts`：

```toml
host = "0.0.0.0"
allow_insecure_bind = true
trusted_hosts = ["localhost", "127.0.0.1", "::1", "vpn.example.com", "203.0.113.10"]
```

重启并限制来源：

```bash
sudo systemctl restart ostium
# 以 Debian/Ubuntu 的 ufw 为例；RHEL 使用 firewalld，见第 10.2 节
sudo ufw allow from 203.0.113.10 to any port 8443 proto tcp
```

验证完成后立即改回回环监听并关闭 8443，再按本文启用 Public UI。

## 3. 部署前准备

### 3.1 DNS

```bash
dig +short A vpn.example.com
dig +short AAAA vpn.example.com
```

- A 记录必须指向服务器公网 IPv4。
- 如果有 AAAA，确认服务器 IPv6 可用且防火墙放行；否则删除 AAAA，避免客户端优先走 IPv6 超时。
- 如果域名在 Cloudflare，Reality/Trojan/Hysteria2 必须使用 **DNS only（灰云）**。橙云只代理 HTTP/HTTPS，会破坏原始 TCP/UDP。管理 UI 想走橙云可以单独用一个域名，但最简单是全部灰云。

### 3.2 证书检查

按实际路径替换：

```bash
sudo openssl x509 -in /etc/letsencrypt/live/vpn.example.com/fullchain.pem \
  -noout -subject -dates -ext subjectAltName
```

确认：

- SAN 包含 `vpn.example.com`；
- 未过期；
- `fullchain.pem` 是完整链；
- 私钥与证书匹配。

如果证书是普通 PEM 文件，放到固定目录：

```bash
sudo install -d -m 0700 /etc/ssl/ostium
sudo install -m 0644 fullchain.pem /etc/ssl/ostium/fullchain.pem
sudo install -m 0600 privkey.pem   /etc/ssl/ostium/privkey.pem
```

Public UI 由 Ostium 直接终止 TLS 时，浏览器必须信任这张证书。Let's Encrypt、ZeroSSL、商业证书可以；Cloudflare Origin CA 只能放在 Cloudflare 橙云后面，不能直接用于公网 UI。自签证书只适合 Hysteria2 pinning 或测试。

### 3.3 基础环境

**Debian / Ubuntu：**

```bash
apt update
apt install -y curl ca-certificates tar ufw
```

普通 sudo 用户：

```bash
sudo apt update
sudo apt install -y curl ca-certificates tar sudo ufw
```

**RHEL / Rocky Linux / AlmaLinux：**

```bash
dnf install -y curl ca-certificates tar firewalld
systemctl enable --now firewalld
```

普通 sudo 用户加 `sudo`。如果是最小化系统，先确认 `curl`、`tar`、`ca-certificates` 已安装。

**Alpine / 非 systemd 系统：**

```bash
apk add curl ca-certificates tar
```

这类系统不要使用本文的 `systemctl`/`journalctl` 命令，安装时加 `--no-service`，按第 4.4 节交给 supervisord 或自己的进程管理器。

时间同步（systemd 发行版）：

```bash
sudo timedatectl set-timezone Asia/Shanghai
sudo timedatectl set-ntp true
timedatectl status
```

非 systemd 发行版请使用 `chronyd`、`ntpd` 或云厂商的时间同步服务。

### 3.4 端口规划

主方案（Public UI 8443）：

- 22/tcp
- 80/tcp
- 443/tcp
- 443/udp
- 8443/tcp
- 需要 Trojan 时再加 9443/tcp

标准 443 变体：

- 22/tcp
- 80/tcp
- 443/tcp
- 443/udp
- 9443/tcp
- 需要 Trojan 时再加 9444/tcp

## 4. 安装 Ostium

### 4.1 root 登录 + 默认非 root 运行

这是推荐组合：安装器以 root 运行，服务以无特权 `ostium` 用户运行。

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/download/v0.1.1/install-online.sh \
  | bash -s -- install \
      --role server \
      --domain vpn.example.com \
      --version 0.1.1
```

### 4.2 普通 sudo 用户 + 默认非 root 运行

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/download/v0.1.1/install-online.sh \
  | sudo bash -s -- install \
      --role server \
      --domain vpn.example.com \
      --version 0.1.1
```

安装器会：

- 安装静态 uv / 托管 Python 3.13；
- 下载并校验 wheel、sdist、sing-box 核心和 `SHA256SUMS`；
- 创建 `ostium` 服务用户；
- 写入 `/opt/ostium`、`/var/lib/ostium`、`/etc/ostium`；
- 注册并启动 `ostium-core.service`、`ostium.service`；
- 打印一次性管理员密码。

不要把 `--public-ui` 加到首次安装命令里。0.1.1 要求先登录、启用 TOTP、上传证书，再从 Settings 开启 Public UI。

安装完成后检查：

```bash
systemctl status ostium-core ostium --no-pager
systemctl show -p User -p Group ostium ostium-core
sudo ss -lntup | grep -E ':(8443|443|9443|8388)\b'
```

默认应看到：

- 两个服务都是 `User=ostium`；
- UI 监听 `127.0.0.1:8443`；
- Reality 监听 `0.0.0.0:443`。

### 4.3 root 运行模式（可选，不推荐生产）

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/download/v0.1.1/install-online.sh \
  | sudo bash -s -- install \
      --role server \
      --domain vpn.example.com \
      --version 0.1.1 \
      --run-as-root
```

行为：

- 不创建 `ostium` 用户；
- 两个 unit 通过 drop-in 改成 `User=root` / `Group=root`；
- 数据仍在 `/var/lib/ostium`，配置仍在 `/etc/ostium`。

验证：

```bash
systemctl show -p User -p Group ostium ostium-core
systemctl cat ostium ostium-core | grep -E 'User=|Group='
```

root 模式取消控制面与 root 的隔离，只建议单用户测试机、临时环境，或已经用容器/虚拟机隔离风险的环境。

### 4.4 非 systemd：`--no-service` + supervisord

安装文件但不注册 systemd：

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/download/v0.1.1/install-online.sh \
  | sudo bash -s -- install \
      --role server \
      --domain vpn.example.com \
      --version 0.1.1 \
      --no-service
```

安装器仍会创建 `ostium` 用户并把数据和配置交给它。

```bash
# Debian / Ubuntu
sudo apt install -y supervisor

# RHEL / Rocky / AlmaLinux（通常需要 EPEL）
sudo dnf install -y epel-release
sudo dnf install -y supervisor

sudo install -d -o ostium -g ostium -m 0750 /var/log/ostium
```

写入 `/etc/supervisor/conf.d/ostium.conf`：

```ini
[program:ostium-core]
command=/opt/ostium/venv/bin/ostium core-run
user=ostium
directory=/var/lib/ostium
environment=OSTIUM_ROLE="server",OSTIUM_CONFIG_FILE="/etc/ostium/config.toml",OSTIUM_DATA_DIR="/var/lib/ostium",OSTIUM_CONFIG_DIR="/etc/ostium"
priority=10
autostart=true
autorestart=true
startsecs=3
stopsignal=TERM
stopasgroup=true
killasgroup=true
stdout_logfile=/var/log/ostium/core.log
stderr_logfile=/var/log/ostium/core.log

[program:ostium]
command=/opt/ostium/venv/bin/ostium serve
user=ostium
directory=/var/lib/ostium
environment=OSTIUM_ROLE="server",OSTIUM_CONFIG_FILE="/etc/ostium/config.toml",OSTIUM_DATA_DIR="/var/lib/ostium",OSTIUM_CONFIG_DIR="/etc/ostium"
priority=20
autostart=true
autorestart=true
startsecs=3
stopsignal=TERM
stopasgroup=true
killasgroup=true
stdout_logfile=/var/log/ostium/ui.log
stderr_logfile=/var/log/ostium/ui.log
```

加载并启动：

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status
sudo supervisorctl tail -f ostium-core
sudo supervisorctl tail -f ostium
```

root 模式下把两个 `user=ostium` 改成 `user=root`，或删除 `user=` 行。

**非 systemd + 非 root 的低端口问题：**

- systemd 单元会给 `ostium`/`ostium-core` 授 `CAP_NET_BIND_SERVICE`，默认模式可以绑定 443。
- supervisord/手动运行没有这个 capability。非 root 绑定 443/tcp 或 443/udp 会失败。
- 两种解决：
  1. 所有入口改用高端口：Reality `9443/tcp`、Hysteria2 `8443/udp`、Trojan `9444/tcp`、UI `8443/tcp`；
  2. 给核心二进制加 capability（升级后要重新加）：
     ```bash
     # Debian / Ubuntu
     sudo apt install -y libcap2-bin
     # RHEL / Rocky / AlmaLinux
     sudo dnf install -y libcap

     sudo setcap cap_net_bind_service=+ep /var/lib/ostium/core/sing-box
     ```

生产上更推荐让 UI 使用 8443，Reality 使用 9443，避免低端口 capability 的维护。

临时前台调试可以这样（两个 SSH 窗口，先核心后 UI）：

```bash
sudo -u ostium env \
  OSTIUM_ROLE=server \
  OSTIUM_CONFIG_FILE=/etc/ostium/config.toml \
  OSTIUM_DATA_DIR=/var/lib/ostium \
  OSTIUM_CONFIG_DIR=/etc/ostium \
  /opt/ostium/venv/bin/ostium core-run
```

```bash
sudo -u ostium env \
  OSTIUM_ROLE=server \
  OSTIUM_CONFIG_FILE=/etc/ostium/config.toml \
  OSTIUM_DATA_DIR=/var/lib/ostium \
  OSTIUM_CONFIG_DIR=/etc/ostium \
  /opt/ostium/venv/bin/ostium serve
```

生产不要用 `nohup` 裸跑，交给 supervisord/runit/s6。

如果只有普通账号且没有 sudo，官方安装器无法使用。不能注册 systemd，不能绑 80/443，也不能改系统防火墙；这种环境不适合公网生产，建议换一台有 root 的服务器。

## 5. 首次登录：用 SSH 隧道打开 127.0.0.1:8443

### 5.1 先理解 127.0.0.1 是什么

`127.0.0.1` 和 `localhost` 都表示**当前正在运行程序的那台机器**。

默认安装后，Ostium 管理 UI 只监听服务器自己的回环地址：

```text
服务器上的 127.0.0.1:8443
```

所以：

- 在服务器上执行 `curl http://127.0.0.1:8443`，访问的是服务器自己，可以通；
- 在你自己的电脑浏览器里输入 `http://127.0.0.1:8443`，访问的是**你自己的电脑**，不是云服务器；
- 直接输入 `http://服务器公网IP:8443`，默认也打不开，因为 Ostium 没有监听公网地址。

要访问服务器的回环地址，需要在你的电脑和服务器之间建立 SSH 隧道：

```text
你的电脑                                     云服务器
浏览器 http://127.0.0.1:8443  --SSH 隧道-->  127.0.0.1:8443
```

### 5.2 第一步：在你自己的电脑上打开终端

不要在云服务器的 SSH 会话里执行下一步的 `ssh -L` 命令。`ssh -L` 必须在你自己的电脑上执行。

- Windows：打开 PowerShell 或 CMD；
- macOS：打开“终端”；
- Linux：打开终端。

### 5.3 第二步：建立 SSH 隧道

root 登录服务器：

```bash
ssh -N -L 8443:127.0.0.1:8443 root@SERVER_IP
```

普通 sudo 用户：

```bash
ssh -N -L 8443:127.0.0.1:8443 youruser@SERVER_IP
```

把 `SERVER_IP` 换成服务器公网 IP，把 `youruser` 换成你的登录用户名。SSH 端口不是 22 时：

```bash
ssh -p 2222 -N -L 8443:127.0.0.1:8443 youruser@SERVER_IP
```

如果使用密钥登录：

```bash
ssh -i ~/.ssh/你的密钥 -N -L 8443:127.0.0.1:8443 youruser@SERVER_IP
```

第一次连接会提示是否信任服务器指纹，输入 `yes`。输入密码时终端不会显示字符，这是正常的。

参数含义：

| 参数 | 作用 |
|---|---|
| `-N` | 只建立隧道，不在服务器上执行命令 |
| `-L 8443:127.0.0.1:8443` | 把本机 8443 转发到服务器的 `127.0.0.1:8443` |
| `root@SERVER_IP` | SSH 登录服务器 |
| `-p 2222` | SSH 端口不是 22 时指定端口 |

执行后终端可能没有任何输出，这是正常的。**不要关闭这个终端窗口**，关闭后隧道就断了。

如果本地 8443 已经被其他程序占用，把本地端口换成 18443：

```bash
ssh -N -L 18443:127.0.0.1:8443 root@SERVER_IP
```

这时浏览器要打开 `http://127.0.0.1:18443`，不是 8443。

### 5.4 第三步：在你自己的电脑浏览器打开

隧道保持运行，在**本地电脑**浏览器打开：

```text
http://127.0.0.1:8443
```

如果上一步用了 18443：

```text
http://127.0.0.1:18443
```

看到登录页就说明隧道成功。用安装器打印的管理员密码登录。

> 注意：默认是 `http://`，不是 `https://`。启用 Public UI 之后才改用 `https://域名`。

### 5.5 第四步：确认服务和隧道都正常

在服务器上确认 Ostium 正在监听回环：

```bash
sudo ss -lntp | grep 8443
```

正常应看到类似：

```text
LISTEN 0 2048 127.0.0.1:8443 ...
```

如果看不到，先检查服务：

```bash
systemctl status ostium --no-pager
journalctl -u ostium -n 100 --no-pager
```

在本地电脑上通过隧道检查：

```bash
curl -I http://127.0.0.1:8443
```

只要返回 HTTP 状态码（例如 `200`、`302`、`401`），就说明隧道通了；如果提示 `Connection refused`，说明隧道没建立或服务没启动。

如果**服务器上** `curl http://127.0.0.1:8443` 能通，但**本地浏览器**打不开，问题在 SSH 隧道，不在 Ostium。

### 5.6 第五步：首次登录后立即做

1. **Settings → Security → TOTP**，扫码绑定，保存恢复码；
2. 修改管理员密码；
3. 暂时不要关闭 SSH 隧道，后面配置证书或 Public UI 出问题还能救；
4. 确认 `http://127.0.0.1:8443/healthz` 返回 `{"status":"ok",...}`。

健康检查：

```bash
curl -fsS http://127.0.0.1:8443/healthz
curl -fsS http://127.0.0.1:8443/readyz
```

`readyz` 里 `core:false` 在还没应用任何入口配置时是正常的；只要 `ready:true` 就说明控制面数据库正常。

### 5.7 Windows 与 PuTTY

Windows 10/11 通常自带 OpenSSH Client，直接在 PowerShell 里执行上面的 `ssh` 命令即可。

如果提示 `ssh` 不是可识别的命令：

1. 设置 → 应用 → 可选功能 → 添加功能；
2. 安装 **OpenSSH Client**；
3. 重新打开 PowerShell。

使用 PuTTY 时：

1. 打开 PuTTY；
2. Connection → SSH → Tunnels；
3. Source port 填 `8443`；
4. Destination 填 `127.0.0.1:8443`；
5. 点 **Add**；
6. 回到 Session，填服务器公网 IP；
7. Open，登录服务器；
8. 在本地浏览器打开 `http://127.0.0.1:8443`。

### 5.8 隧道常见错误

| 现象 | 原因 | 处理 |
|---|---|---|
| `bind: Address already in use` | 本地 8443 被占用 | 改用 `-L 18443:127.0.0.1:8443`，浏览器也改用 18443 |
| `Connection refused` | SSH 端口不对/服务未启动 | 检查 `-p`、服务器 SSH 端口、`systemctl status ostium` |
| `Permission denied` | 用户名/密钥/密码不对 | 用正确的 sudo 用户和密钥；root 登录可能被禁用 |
| `Connection timed out` | 公网 IP/安全组/SSH 端口不通 | 检查云安全组和本机网络 |
| 浏览器 `ERR_CONNECTION_REFUSED` | 隧道终端已关闭，或浏览器开在服务器上 | 重新建隧道；浏览器必须在你自己的电脑上 |
| 浏览器打开是别的页面 | 本地 8443 被其他程序占用 | 换本地端口 18443 |
| 浏览器自动跳到 `https://127.0.0.1:8443` | 浏览器开启了 HTTPS-only 模式 | 手动输入 `http://`，或临时关闭 HTTPS-only |
| 登录页能开但登录后掉线 | 隧道正常，但后面启用了 Secure Cookie | 启用 Public UI 后用 HTTPS 域名访问 |

### 5.9 不要为了打开 8443 把它暴露到公网

SSH 隧道已经足够完成首次登录。不要把 8443 直接开放给公网，也不要把 `host` 改成 `0.0.0.0` 来图方便。完成首次设置后，按第 7 节启用 Public UI，用域名 + TLS 访问。

## 6. 上传证书

Reality 不需要证书。只有 Hysteria2、Trojan 和 Ostium 自己终止 TLS 的 Public UI 需要。

从服务器取出 PEM：

```bash
sudo cat /etc/letsencrypt/live/vpn.example.com/fullchain.pem
sudo cat /etc/letsencrypt/live/vpn.example.com/privkey.pem
```

如果证书在 `/etc/ssl/ostium/`：

```bash
sudo cat /etc/ssl/ostium/fullchain.pem
sudo cat /etc/ssl/ostium/privkey.pem
```

Ostium 的 Upload 表单是**粘贴 PEM 文本**，不是填写服务器文件路径。把两段内容分别粘贴到两个文本框。私钥不要发到聊天、日志或公开仓库。

操作步骤：

1. 登录 Ostium；
2. **Certificates → Upload**；
3. Domain 填 `vpn.example.com`；
4. Cert PEM 粘贴 `fullchain.pem` 全文；
5. Key PEM 粘贴 `privkey.pem` 全文；
6. 保存；
7. 点 **Use** 分配给 Hysteria2/Trojan，或稍后在 **Inbounds** 里选择。

要求：

- 证书和私钥匹配；
- 证书覆盖该域名；
- 未过期；
- 私钥未加密（有 passphrase 的先解密）；
- `fullchain.pem` 包含中间证书。

### 6.1 续期注意

**手动上传的证书不会自动续期。** Ostium 只会自动续期 `source=acme` 的证书。

三种做法：

1. 用 Ostium 内置 ACME（**Certificates → Issue → ACME HTTP-01**），需要 80/tcp 空闲；它每 6 小时检查，剩余不足 30 天自动续；
2. 用 certbot/acme.sh 续期后，重新上传新证书；
3. 只使用 Reality 时，代理入口不需要证书；管理 UI 的证书单独由 Public UI/证书续期流程处理。

如果 80 被其他程序占用，Ostium 内置 ACME 会报 `port_80_unavailable`，这时用 certbot 或临时停占用者。

## 7. 启用 Public UI（主方案，8443）

1. 已完成：上传证书、启用 TOTP；
2. 打开 **Settings → Public admin UI**；
3. Domain 填 `vpn.example.com`；
4. 开启并保存；
5. 重启：

```bash
sudo systemctl restart ostium
```

6. 确认监听：

```bash
sudo ss -lntp | grep 8443
```

应看到 `0.0.0.0:8443`，而不是只有 `127.0.0.1:8443`。

7. 放行 8443/tcp（下面以 Debian/Ubuntu 的 ufw 为例；RHEL 系见第 10.2 节）：

```bash
sudo ufw allow 8443/tcp
```

8. 打开：

```text
https://vpn.example.com:8443
```

9. **Settings → Public base URL** 必须填：

```text
https://vpn.example.com:8443
```

这一步很容易漏。默认 `public_base_url` 可能是 `https://vpn.example.com`，订阅链接会指向 443，而 UI 在 8443，客户端会拉不到订阅。

> Public UI 直接终止 TLS，不要再在同一台机器上让 Nginx 占用 8443/443 做同一个域名的反代。两者选一个。

## 8. 标准 443 变体（不装 Nginx）

如果必须使用 `https://vpn.example.com`，不带端口：

1. **Inbounds → Reality → 端口改为 9443 → 保存/应用**；
2. 确认核心应用成功；
3. 编辑配置：

```bash
sudo nano /etc/ostium/config.toml
```

把：

```toml
port = 8443
```

改成：

```toml
port = 443
```

4. 重启：

```bash
sudo systemctl restart ostium
```

5. 确认 UI 在 `127.0.0.1:443`，Reality 在 `9443`：

```bash
sudo ss -lntp | grep -E ':(443|9443)\b'
```

6. 上传证书、启用 TOTP；
7. **Settings → Public admin UI** 填 `vpn.example.com` 并开启；
8. 再重启：

```bash
sudo systemctl restart ostium
```

9. 放行（下面以 Debian/Ubuntu 的 ufw 为例；RHEL 系见第 10.2 节）：

```bash
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw allow 9443/tcp
```

10. 打开：

```text
https://vpn.example.com
```

11. **Settings → Public base URL** 填：

```text
https://vpn.example.com
```

如果启动失败，先看：

```bash
journalctl -u ostium -n 100 --no-pager
```

最常见原因是 443 还被 Reality/Nginx 占用，或证书/TOTP 未就绪。

## 9. 配置代理入口

进入 **Inbounds** 页面。

### 9.1 Reality

- 默认已启用；
- 主方案保持 `443/tcp`；标准 443 变体改 `9443/tcp`；
- 不需要证书；
- 保存后应用；
- 改了端口后，防火墙放行新端口；
- 已有用户需要重新复制订阅，客户端才会拿到新端口。

### 9.2 Hysteria2（可选）

- 启用；
- 端口 `443/udp`；
- 选择刚上传的证书；
- 保存/应用；
- 防火墙和云安全组放行 UDP 443；
- 如果 Nginx 开了 HTTP/3（`listen 443 quic`），把 Hysteria2 改到 `8443/udp`。

### 9.3 Trojan（可选）

- 启用；
- 端口不能和 Reality 共用 TCP 443。主方案用 `9443/tcp`，标准 443 变体用 `9444/tcp`；
- 选择证书；
- 保存/应用；
- 放行对应 TCP 端口。

### 9.4 Shadowsocks 2022（可选）

- 默认关闭，端口 `8388`；
- 需要时再启用；
- 放行 `8388/tcp` 和 `8388/udp`；
- 不需要证书。

### 9.5 创建用户和订阅

1. **Users → Add user**；
2. 填用户名、配额、到期时间；
3. 勾选要启用的协议/入口；
4. 保存；
5. 复制订阅 URL 或二维码。

订阅 URL 是敏感信息，等同于账号密码。

客户端：

- Windows：`Ostium-0.1.1-windows-x64-setup.exe`
- macOS：`Ostium-0.1.1-macos-arm64.dmg`
- Linux：在线安装器 `install --role client`，或 DEB/AppImage
- 也可以用 Clash/sing-box/v2rayN 等兼容客户端导入订阅

客户端导入订阅后：

1. 选择配置；
2. 连接；
3. 打开 `https://ipinfo.io` 确认出口 IP 是服务器；
4. 做一次 DNS 泄漏测试；
5. 如果走 TUN，确认客户端有管理员/root 权限。

## 10. 防火墙与验证

下面以主方案（Public UI 8443）为例。标准 443 变体把 8443 换成 443，并保留 9443/9444。

### 10.1 Debian / Ubuntu（ufw）

主方案：

```bash
sudo ufw default deny incoming
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw allow 8443/tcp
# 如果启用 Trojan
sudo ufw allow 9443/tcp
sudo ufw --force enable
sudo ufw status verbose
```

标准 443 变体：

```bash
sudo ufw default deny incoming
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw allow 9443/tcp
# 如果启用 Trojan
sudo ufw allow 9444/tcp
sudo ufw --force enable
```

### 10.2 RHEL / Rocky / AlmaLinux（firewalld）

主方案：

```bash
sudo systemctl enable --now firewalld
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --add-port=443/udp
sudo firewall-cmd --permanent --add-port=8443/tcp
# 如果启用 Trojan
sudo firewall-cmd --permanent --add-port=9443/tcp
sudo firewall-cmd --reload
sudo firewall-cmd --list-all
```

标准 443 变体：

```bash
sudo systemctl enable --now firewalld
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --add-port=443/udp
sudo firewall-cmd --permanent --add-port=9443/tcp
# 如果启用 Trojan
sudo firewall-cmd --permanent --add-port=9444/tcp
sudo firewall-cmd --reload
sudo firewall-cmd --list-all
```

云厂商安全组也要放行同样端口；只改本机防火墙不够。不要把 8443 暴露给全世界，能限制来源 IP 就限制。

### 10.3 从本地验证

在本地电脑上：

```bash
curl -I https://vpn.example.com:8443
curl -fsS https://vpn.example.com:8443/healthz
curl -fsS https://vpn.example.com:8443/readyz
```

标准 443 变体：

```bash
curl -I https://vpn.example.com
curl -fsS https://vpn.example.com/healthz
```

服务器上检查监听：

```bash
sudo ss -lntup | grep -E ':(22|80|443|8443|9443|9444|8388)\b'
```

## 11. 日常运维

### 11.1 systemd

```bash
systemctl status ostium-core ostium --no-pager
journalctl -u ostium-core -u ostium -f
sudo systemctl restart ostium-core ostium
sudo systemctl restart ostium          # 只改了 UI 配置/TLS 时
```

### 11.2 supervisord

```bash
sudo supervisorctl status
sudo supervisorctl restart ostium-core ostium
sudo supervisorctl tail -f ostium
sudo supervisorctl tail -f ostium-core
```

日志：

```bash
tail -f /var/log/ostium/ui.log
tail -f /var/log/ostium/core.log
```

### 11.3 诊断

默认非 root 模式：

```bash
sudo -u ostium env \
  OSTIUM_ROLE=server \
  OSTIUM_CONFIG_FILE=/etc/ostium/config.toml \
  OSTIUM_DATA_DIR=/var/lib/ostium \
  OSTIUM_CONFIG_DIR=/etc/ostium \
  /opt/ostium/venv/bin/ostium doctor
```

```bash
sudo -u ostium env \
  OSTIUM_ROLE=server \
  OSTIUM_CONFIG_FILE=/etc/ostium/config.toml \
  OSTIUM_DATA_DIR=/var/lib/ostium \
  OSTIUM_CONFIG_DIR=/etc/ostium \
  /opt/ostium/venv/bin/ostium status
```

root 模式把 `sudo -u ostium` 去掉。

### 11.4 备份

最省事：UI **Settings → Backup**。

命令行：

```bash
sudo -u ostium env \
  OSTIUM_ROLE=server \
  OSTIUM_CONFIG_FILE=/etc/ostium/config.toml \
  OSTIUM_DATA_DIR=/var/lib/ostium \
  OSTIUM_CONFIG_DIR=/etc/ostium \
  /opt/ostium/venv/bin/ostium backup create --password '一个长口令'
```

备份在 `/var/lib/ostium/backups`。备份包含 `master.key`，等同于最高敏感文件，必须异地保存并加密。

升级前一定先备份。

### 11.5 升级

systemd：

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/download/v0.1.1/install-online.sh \
  | sudo bash -s -- upgrade
```

指定版本：

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/download/v0.1.1/install-online.sh \
  | sudo bash -s -- upgrade --version 0.1.2
```

root 模式安装器会自动识别 drop-in 并保持 root；如果没识别，显式加 `--run-as-root`。

非 systemd：

```bash
sudo supervisorctl stop ostium ostium-core
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/download/v0.1.1/install-online.sh \
  | sudo bash -s -- upgrade --no-service
sudo supervisorctl start ostium-core ostium
```

### 11.6 卸载

保留数据：

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/download/v0.1.1/install-online.sh \
  | sudo bash -s -- uninstall
```

同时删除数据/配置/证书（不可恢复）：

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/download/v0.1.1/install-online.sh \
  | sudo bash -s -- uninstall --purge
```

非 systemd 还要删除 `/etc/supervisor/conf.d/ostium.conf` 并执行 `sudo supervisorctl update`。

### 11.7 安全底线

- 生产不要用 `--run-as-root`；
- 管理 UI 不要裸奔在公网 HTTP；
- Public UI 必须先 TOTP + 有效证书；
- 只开必要端口；
- 定期备份，备份包含 `master.key`；
- 证书续期要有监控；
- SSH 用密钥登录，禁用密码登录。

可选 BBR：

```bash
sudo tee /etc/sysctl.d/99-ostium.conf >/dev/null <<'EOF'
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
EOF
sudo sysctl --system
```

## 12. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 浏览器打不开 `127.0.0.1:8443` | SSH 隧道没开/本地端口占用 | 重开 `ssh -N -L ...`，或换本地端口 |
| `http://公网IP:8443` 打不开 | 默认只监听回环 | 用 SSH 隧道；不要为此改成公网明文 |
| `400 invalid Host header` | `trusted_hosts` 不含当前 Host | 用域名访问；把域名加入 `trusted_hosts` |
| `refusing to expose the admin UI ... plaintext` | 非回环明文绑定被拒绝 | 用回环 + SSH 隧道，或 Public UI |
| Public UI 启动失败，日志提示 TOTP | 未启用 TOTP | 先启用 TOTP，再开 Public UI |
| Public UI 启动失败，提示 no certificate | 证书未上传/未 ready/域名不匹配 | 上传该域名的有效证书 |
| 登录成功立刻掉线 | `secure_cookies=true` 但用 HTTP/隧道访问 | 用 HTTPS 域名访问；临时调试可改 false |
| `port_80_unavailable` | 其他程序占用 80 | 用 certbot，或临时停占用者 |
| `address already in use` | UI 和 Reality 同时占 443/tcp | 先移动 Reality 到 9443 |
| 非 root 手动运行绑 443 失败 | 没有 `CAP_NET_BIND_SERVICE` | 用 9443/8443 高端口，或 `setcap` |
| 客户端连不上/订阅 404 | `public_base_url` 不对，或端口改了没换订阅 | 改 Public base URL，重新复制订阅 |
| Cloudflare 橙云后代理不通 | 橙云只代理 HTTP/HTTPS | VPN 域名改 DNS only（灰云） |
| 较旧发行版装 DEB/AppImage 报 glibc | PyInstaller 产物依赖构建环境的 glibc | 用在线安装器/wheel，不要用 DEB/AppImage |
| 服务启动但核心离线 | 入口配置未应用/证书缺失/端口冲突 | 看 UI Logs、`journalctl -u ostium-core` |

## 13. Nginx 可选附录

只有已经运行 Nginx，或需要同机托管其他 HTTPS 网站时才使用。完整配置见 [Nginx 共存与反向代理](nginx.md)。

要点：

1. Nginx 占 443/tcp，Ostium UI 保持 `127.0.0.1:8443`；
2. Reality 改到 `9443/tcp`，Hysteria2 保持 `443/udp`；
3. 安装 Ostium 时可以加 `--behind-proxy`，或安装后手动设置：

   ```toml
   host = "127.0.0.1"
   port = 8443
   public_ui = false
   secure_cookies = true
   trusted_hosts = ["localhost", "127.0.0.1", "::1", "vpn.example.com"]
   ```

4. Nginx 反代到 `http://127.0.0.1:8443`；
5. 保留 `Host`、`X-Forwarded-For`、`X-Forwarded-Proto`、WebSocket 的 `Upgrade`/`Connection` 头；
6. 访问 `https://vpn.example.com`；
7. 不要把 Public UI 和 Nginx 同时开在同一个 443 端口上。

## 14. 最短命令清单（主方案）

```bash
# 1. DNS 灰云，证书路径确认
# 2. 安装（root 登录去掉 sudo）
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/download/v0.1.1/install-online.sh \
  | sudo bash -s -- install --role server --domain vpn.example.com --version 0.1.1

# 3. SSH 隧道登录
ssh -N -L 8443:127.0.0.1:8443 root@SERVER_IP
# 浏览器 http://127.0.0.1:8443

# 4. UI：启用 TOTP → 上传证书

# 5. UI：Settings → Public admin UI → 域名 → 开启
sudo systemctl restart ostium

# 6. 放行 8443（以 Debian/Ubuntu 的 ufw 为例；RHEL 系见第 10.2 节）
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw allow 8443/tcp
sudo ufw --force enable

# 7. 验证
curl -fsS https://vpn.example.com:8443/healthz

# 8. UI：创建用户 → 复制订阅 → 客户端导入
```
