# 从零部署中文教程

这篇教程按顺序完成一台 **Linux 单机 Ostium Server** 的生产部署。目标读者是第一次接触 Ostium、但熟悉基本 Linux 命令的管理员。

教程提供两条路线：

| 路线 | 适用场景 | 管理面入口 | 证书 |
|---|---|---|---|
| A. systemd + Caddy | 推荐，单机长期运行 | `https://域名:8443/` | 安装器可代申请 Let's Encrypt |
| B. Docker Compose + Caddy | 已熟悉 Docker，或希望容器隔离 | `https://域名:8443/` | 需在宿主机提前准备证书 |
| C. 仅 SSH 隧道 | 无公网域名、只自己用 | `http://127.0.0.1:8000/` | 不需要 |

> Ostium 0.2.0 是服务端-only 重写。没有 0.1.x 迁移、没有客户端、没有 TUN。
> 旧实例不能升级到 0.2.0，只能全新安装、重新建用户、重新发订阅。

---

## 0. 准备清单

开始前确认：

- [ ] 一台 Debian 13 / Ubuntu 24.04+ 的 Linux 服务器，root 或 sudo。
- [ ] 一个域名，例如 `vpn.example.com`，A/AAAA 记录指向服务器公网 IP。
- [ ] 防火墙可放行 `22/tcp`、`80/tcp`、`443/tcp`、`443/udp`、`8443/tcp`。
- [ ] 服务器能访问外网（下载 Python、Go、sing-box 源码、Let's Encrypt）。
- [ ] 一个可用的证书联系邮箱；当前安装器默认使用 `admin@<域名>`。

### 端口规划

| 端口 | 用途 | 是否必须 |
|---|---|---|
| `22/tcp` | SSH | 必须 |
| `80/tcp` | ACME HTTP-01 / Caddy 跳转 | 首次签发和续期需要 |
| `443/tcp` | VLESS Reality / Trojan | 代理必须 |
| `443/udp` | Hysteria2 | 启用 Hysteria2 时 |
| `8443/tcp` | Caddy 管理面 TLS | 使用 Caddy 时 |
| `8388/tcp` | Shadowsocks 2022 | 启用 SS 时 |

> 一个 TCP 端口只能给一个 TCP 线路。VLESS 和 Trojan 默认都想用 `443/tcp`，
> 同时启用时必须把其中一个改到别的端口，例如 Trojan 用 `9443/tcp`。
> Hysteria2 是 UDP，可以和 VLESS 共用数字端口 443。

### DNS 检查

在本地电脑执行：

```bash
dig +short vpn.example.com
```

必须返回服务器公网 IP。DNS 未生效前不要申请证书。

---

## 1. 路线 A：systemd + Caddy

### 1.1 安装系统依赖

Ostium 安装器不会自动安装 Caddy 和 certbot，需要先装好：

```bash
sudo apt update
sudo apt install -y ca-certificates curl openssl git certbot
```

安装 Caddy（官方仓库）：

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
sudo chmod o+r /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

确认：

```bash
caddy version
certbot --version
```

启用 certbot 定时器：

```bash
sudo systemctl enable --now certbot.timer
```

### 1.2 放行防火墙

以 UFW 为例：

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw allow 8443/tcp
# 只有启用 Shadowsocks 时才需要：
# sudo ufw allow 8388/tcp
sudo ufw enable
sudo ufw status
```

云服务器还要在安全组放行同样端口。

### 1.3 一键在线安装

不需要手动下载 `install.sh`：

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

脚本会自动下载源码、构建 sing-box、安装 systemd 服务和申请证书。

更稳妥的方式是先看脚本再执行：

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  -o /tmp/ostium-install.sh
less /tmp/ostium-install.sh
sudo bash /tmp/ostium-install.sh --domain vpn.example.com --with-caddy
```

也可以手动 clone：

```bash
git clone https://github.com/ThzxxArt/Ostium.git
cd Ostium
sudo bash install.sh --domain vpn.example.com --with-caddy
```

安装器会：

1. 安装运行时依赖，下载固定版本 `uv` 与 Python 3.14 到 `/opt/ostium`。
2. 安装本仓库到 `/opt/ostium/venv`。
3. 从 sing-box `v1.14.4` 源码构建带统计标签的数据面二进制。
4. 创建 `ostium` 系统用户、`/var/lib/ostium`、`/etc/ostium`。
5. 生成 `OSTIUM_SECRET_KEY`、`OSTIUM_FIELD_KEY`、`/etc/ostium/ostium.env`。
6. 执行 migrate、collectstatic、init，并打印一次性管理员密码。
7. 安装并启动 `ostium-web`、`ostium-worker`、`ostium-jobs`。
8. 如果证书不存在，用 certbot standalone 申请证书。
9. 把证书复制到 `/etc/ostium/tls/vpn.example.com/`，配置 Caddy 8443。
10. 安装证书续期 pre/post/deploy hook，并启用 `certbot.timer`。

> 首次安装需要下载 Go/sing-box 源码并编译，通常 3–10 分钟。
> 如果 certbot 申请失败，先检查 DNS、80 端口和安全组。

记下安装器输出的：

```text
Initial administrator password: ...
```

### 1.4 安装后检查

```bash
sudo systemctl status ostium-web ostium-worker ostium-jobs --no-pager
sudo -u ostium /usr/local/bin/ostium doctor
sudo -u ostium /usr/local/bin/ostium status
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/readyz
```

浏览器打开：

```text
https://vpn.example.com:8443/
```

首次登录会强制修改密码。修改后进入「系统」或直接访问：

```text
https://vpn.example.com:8443/accounts/totp/setup/
```

绑定 TOTP，并把 10 个恢复码离线保存。**公网管理面必须启用 TOTP。**

如果使用自签或测试证书，浏览器会告警；公网生产环境请使用正式证书。

---

## 2. 首次配置

### 2.1 创建第一个用户

控制台：

```text
用户 -> 新增用户
```

或 CLI：

```bash
sudo -u ostium /usr/local/bin/ostium user add alice \
  --quota 100G --cycle monthly --note "first user"
```

默认只显示打码 token。需要完整订阅链接时：

```bash
sudo -u ostium /usr/local/bin/ostium user subscription alice --reveal
```

### 2.2 启用线路

控制台「线路」页，或 CLI：

```bash
sudo -u ostium /usr/local/bin/ostium inbound list
sudo -u ostium /usr/local/bin/ostium inbound enable vless
```

默认：

- VLESS Reality：`443/tcp`，不需要证书，建议默认启用。
- Hysteria2：`443/udp`，需要证书。
- Trojan：`443/tcp`，需要证书；和 VLESS 同端口冲突时必须改端口。
- Shadowsocks 2022：`8388/tcp`，不需要证书，默认关闭。

修改端口：

```bash
sudo -u ostium /usr/local/bin/ostium inbound set-port trojan 9443
sudo -u ostium /usr/local/bin/ostium apply
```

### 2.3 证书分配给 Hysteria2 / Trojan

Caddy 的 certbot deploy hook 会把证书同步进 Ostium。控制台「证书」页应能看到
`vpn.example.com`。然后：

1. 打开「线路」。
2. 编辑 Hysteria2 或 Trojan。
3. 选择证书 `vpn.example.com`。
4. 保存并等待「已应用」。

也可以手动导入：

```text
Django Admin -> Certificates -> Import certificate
```

或 CLI：

```bash
sudo -u ostium /usr/local/bin/ostium cert import \
  --domain vpn.example.com \
  --cert /etc/letsencrypt/live/vpn.example.com/fullchain.pem \
  --key /etc/letsencrypt/live/vpn.example.com/privkey.pem
```

### 2.4 获取订阅

用户详情页点击「显示完整链接」，或：

```bash
sudo -u ostium /usr/local/bin/ostium user subscription alice --reveal
```

四种格式：

```text
https://vpn.example.com:8443/sub/<token>               Base64，v2rayN/Shadowrocket
https://vpn.example.com:8443/sub/<token>/clash         Clash/Mihomo
https://vpn.example.com:8443/sub/<token>/singbox       sing-box 官方客户端
https://vpn.example.com:8443/sub/<token>?target=uri    纯 URI
```

把对应链接导入客户端。订阅 token 等同密码，不要发到公开群组。

### 2.5 客户端导入

| 客户端 | 使用 |
|---|---|
| v2rayN / v2rayNG / Shadowrocket / NekoBox | 默认 Base64 链接 |
| Clash Verge Rev / Mihomo Party / OpenClash | `/clash` |
| sing-box 官方客户端 | `/singbox` |
| 手动调试 | `?target=uri` |

导入后访问一个公网网站验证。若失败，先看「连接」页是否有会话，再看
`/var/lib/ostium/logs/sing-box.log`。

---

## 3. 证书续期与验证

### 3.1 手动验证续期

```bash
sudo certbot renew --dry-run
sudo systemctl status certbot.timer
```

续期流程：

```text
certbot.timer
  -> pre hook: 停止 Caddy，释放 80
  -> certbot standalone 续期
  -> post hook: 复制证书到 /etc/ostium/tls，启动 Caddy
  -> deploy hook: 暂存证书并执行 ostium cert sync
  -> worker 应用新证书
```

查看 Caddy：

```bash
sudo systemctl status caddy --no-pager
sudo journalctl -u caddy -n 100 --no-pager
sudo bash -c 'set -a; . /etc/ostium/ostium.env; set +a; caddy validate --config /etc/caddy/Caddyfile'
```

查看证书：

```bash
sudo openssl x509 -in /etc/ostium/tls/vpn.example.com/fullchain.pem \
  -noout -subject -issuer -dates
```

### 3.2 已有证书

如果已经用 certbot 申请过，只要保证：

```text
/etc/letsencrypt/live/vpn.example.com/fullchain.pem
/etc/letsencrypt/live/vpn.example.com/privkey.pem
```

存在，再执行安装器即可；它会跳过申请，直接复制并配置。

如果证书不在 certbot 目录，先导入 Ostium，再在 Caddyfile 中指向你的路径；
或者把证书放到 `/etc/ostium/tls/vpn.example.com/` 后重启 Caddy。

---

## 4. 备份、升级、回滚

### 4.1 创建加密备份

```bash
sudo -u ostium /usr/local/bin/ostium backup create \
  --password 'a-long-backup-password'
```

备份包含数据库、证书、当前配置和字段密钥，使用 scrypt + AES-256-GCM 加密。
把 `.ostb` 复制到另一台机器或对象存储。

自动备份：

```bash
# /etc/ostium/ostium.env
OSTIUM_BACKUP_PASSWORD=...
```

然后在控制台「设置」启用 `auto_backup_enabled`，保留份数由
`auto_backup_keep` 控制（默认 7）。

### 4.2 升级

在线升级不需要本地 checkout：

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --ref main
```

或从本地 checkout 升级：

```bash
cd Ostium
git pull
sudo bash install.sh upgrade --from-source
```

如果 `/etc/ostium/ostium.env` 中有 `OSTIUM_BACKUP_PASSWORD`，安装器会先创建
pre-upgrade 备份；否则会警告并继续。

升级会重启 web/worker/jobs，隧道可能中断 1–3 秒。

### 4.3 回滚

```bash
sudo systemctl stop ostium-web ostium-worker ostium-jobs
sudo -u ostium /usr/local/bin/ostium backup restore \
  /var/lib/ostium/backups/ostium-backup-....ostb \
  --password '...'
sudo systemctl start ostium-web ostium-worker ostium-jobs
```

恢复会替换当前数据库与证书；操作前先备份当前状态。

### 4.4 卸载

```bash
sudo bash install.sh uninstall          # 保留数据
sudo bash install.sh uninstall --purge  # 删除数据、配置、用户
```

---

## 5. 路线 B：Docker Compose + Caddy

### 5.1 安装 Docker

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker
docker version
docker compose version
```

### 5.2 准备正式证书

Compose 的 Caddy 容器不运行 certbot，需要宿主机提前签发：

```bash
sudo apt install -y certbot
sudo systemctl stop caddy 2>/dev/null || true
sudo certbot certonly --standalone \
  -d vpn.example.com \
  -m admin@example.com \
  --agree-tos --non-interactive
```

复制到 Caddy 容器可读的位置：

```bash
sudo install -d -m 0750 /etc/ostium/tls/vpn.example.com
sudo install -m 0600 -o root -g root \
  /etc/letsencrypt/live/vpn.example.com/fullchain.pem \
  /etc/ostium/tls/vpn.example.com/fullchain.pem
sudo install -m 0600 -o root -g root \
  /etc/letsencrypt/live/vpn.example.com/privkey.pem \
  /etc/ostium/tls/vpn.example.com/privkey.pem
```

> Caddy 官方镜像默认以 root 运行；如果你自定义了 `user:`，请把证书组权限
> 调整为该用户可读。

### 5.3 配置环境变量

```bash
cd Ostium/deploy/docker
cp ostium.env.example ostium.env
```

编辑 `ostium.env`：

```dotenv
OSTIUM_SECRET_KEY=<openssl rand -hex 32>
OSTIUM_FIELD_KEY=<openssl rand -base64 32>
OSTIUM_ALLOWED_HOSTS=vpn.example.com,localhost,127.0.0.1
OSTIUM_CSRF_TRUSTED_ORIGINS=https://vpn.example.com:8443
OSTIUM_PUBLIC_BASE_URL=https://vpn.example.com:8443
OSTIUM_BEHIND_PROXY=true
OSTIUM_SECURE_COOKIES=true
OSTIUM_REQUIRE_TOTP=true
OSTIUM_BACKUP_PASSWORD=<强密码>
```

生成密钥：

```bash
openssl rand -hex 32
openssl rand -base64 32
```

Caddy profile 还需要 Compose 插值变量（不是 service 的 `env_file`）：

```bash
export OSTIUM_DOMAIN=vpn.example.com
export OSTIUM_ACME_EMAIL=admin@example.com
```

也可以把它们写进 `deploy/docker/.env`，Compose 会自动读取。

### 5.4 启动

先启动 web/worker/jobs：

```bash
cd Ostium/deploy/docker
docker compose up -d --build web worker jobs
docker compose ps
```

首次初始化：

```bash
docker compose exec web ostium init --username admin
```

记下一次性密码，打开：

```text
https://vpn.example.com:8443/
```

绑定 TOTP 后，再启动 Caddy：

```bash
docker compose --profile caddy up -d caddy
docker compose ps
```

> 必须先有证书再启动 caddy profile；否则 Caddy 会因找不到证书启动失败。

### 5.5 检查

```bash
docker compose ps
docker compose logs --no-color web worker
docker compose exec web ostium doctor
docker compose exec web ostium status
```

管理面在容器内部是 `web:8000`，Caddy 通过 `web:8000` 反代；浏览器访问
`https://vpn.example.com:8443/`。

### 5.6 Docker 证书续期

```bash
sudo certbot renew
sudo install -m 0600 -o root -g root \
  /etc/letsencrypt/live/vpn.example.com/fullchain.pem \
  /etc/ostium/tls/vpn.example.com/fullchain.pem
sudo install -m 0600 -o root -g root \
  /etc/letsencrypt/live/vpn.example.com/privkey.pem \
  /etc/ostium/tls/vpn.example.com/privkey.pem
docker compose restart caddy
```

建议把这三步写成宿主机 certbot deploy hook。

### 5.7 Docker 使用 PostgreSQL

```bash
# deploy/docker/ostium.env
OSTIUM_DB_URL=postgres://ostium:secret@postgres:5432/ostium
POSTGRES_PASSWORD=secret
```

先启动数据库：

```bash
docker compose --profile postgres up -d postgres
docker compose --profile postgres ps
```

等 postgres healthy 后，再启动 web/worker/jobs：

```bash
docker compose --profile postgres up -d web worker jobs
```

SQLite 数据必须放本机卷，不要放 NFS。

---

## 6. 路线 C：只用 SSH 隧道

没有公网域名时：

```bash
# 服务器：不带 --domain / --with-caddy，服务只监听回环
cd Ostium
sudo bash install.sh

# 本地电脑
ssh -L 8000:127.0.0.1:8000 user@server
```

浏览器打开 `http://127.0.0.1:8000/`。

此方式：

- 不需要 Caddy、certbot、正式证书；
- 管理面只监听回环；
- 代理端口仍需公网放行 443/tcp、443/udp。

---

## 7. 公网安全清单

上线前逐项确认：

- [ ] 域名 A/AAAA 正确，80/443/8443 安全组已放行。
- [ ] `OSTIUM_REQUIRE_TOTP=true`，管理员已绑定 TOTP 并保存恢复码。
- [ ] `OSTIUM_ALLOWED_HOSTS` 只包含真实域名与本机回环。
- [ ] `OSTIUM_CSRF_TRUSTED_ORIGINS` 是 `https://域名:8443`。
- [ ] `OSTIUM_BEHIND_PROXY=true`、`OSTIUM_SECURE_COOKIES=true`。
- [ ] Caddy 使用正式证书，`certbot renew --dry-run` 成功。
- [ ] `ostium doctor` 没有 fail。
- [ ] 已创建并异地保存加密备份。
- [ ] 防火墙只放行必要端口。
- [ ] 没有把 `.env`、数据库、证书私钥提交到 git。

---

## 8. 排障

### 安装器提示缺少 caddy/certbot

```text
Install caddy first / Install certbot first
```

按 1.1 节安装后重试。安装器不会自动 apt 安装这两个软件。

### certbot 申请失败

检查：

```bash
dig +short vpn.example.com
sudo ss -ltnp | grep ':80 '
sudo systemctl status caddy --no-pager
```

常见原因：DNS 未生效、80 被占用、云安全组未放行、域名已被其他证书占用。

### 浏览器 502

```bash
curl -v http://127.0.0.1:8000/healthz
sudo systemctl status ostium-web --no-pager
sudo journalctl -u caddy -n 100 --no-pager
```

Caddy 到 web 的 upstream 默认 `127.0.0.1:8000`；Docker 下是 `web:8000`。

### 表单提交 403 CSRF

确认：

```dotenv
OSTIUM_CSRF_TRUSTED_ORIGINS=https://vpn.example.com:8443
OSTIUM_PUBLIC_BASE_URL=https://vpn.example.com:8443
```

Caddy 的 `Referrer-Policy` 应为 `same-origin`，订阅响应单独 `no-referrer`。

### 订阅 403 / 404 / 429

- 403：用户禁用、到期、超配额，或没有可用线路/证书。
- 404：token 错误或已轮换。
- 429：IP 60/min 或 token 120/min，等待 `Retry-After`。

### 统计为 0

```bash
sudo -u ostium /usr/local/bin/ostium status
sudo ss -ltnp | grep 19091
```

确认 sing-box 是带 `with_v2ray_api` 的构建；官方 release 不含该标签。
第一次采样只建立基线，产生流量后 5–60 秒写入。

### worker 无法绑定 443

检查：

```bash
systemctl cat ostium-worker
journalctl -u ostium-worker -n 100 --no-pager
```

unit 通过 `AmbientCapabilities=CAP_NET_BIND_SERVICE` 绑定 443，不需要 root。

### 恢复后凭据不可读

Ostium 恢复时会用备份中的字段密钥解密，再用当前 `OSTIUM_FIELD_KEY` 重加密。
如果仍失败，确认备份完整、密码正确，并查看 `ostium backup restore` 输出。

---

## 9. 常用命令速查

```bash
# 服务
sudo systemctl status ostium-web ostium-worker ostium-jobs
sudo systemctl restart ostium-worker
sudo journalctl -u ostium-worker -f

# 状态
sudo -u ostium /usr/local/bin/ostium doctor
sudo -u ostium /usr/local/bin/ostium status --json

# 用户
sudo -u ostium /usr/local/bin/ostium user list
sudo -u ostium /usr/local/bin/ostium user add alice --quota 100G
sudo -u ostium /usr/local/bin/ostium user subscription alice --reveal
sudo -u ostium /usr/local/bin/ostium user rotate alice --subscription --reveal
sudo -u ostium /usr/local/bin/ostium user reset-usage alice

# 线路
sudo -u ostium /usr/local/bin/ostium inbound list
sudo -u ostium /usr/local/bin/ostium inbound set-port trojan 9443
sudo -u ostium /usr/local/bin/ostium apply

# 证书
sudo -u ostium /usr/local/bin/ostium cert list
sudo -u ostium /usr/local/bin/ostium cert sync --dir /var/lib/ostium/imports/letsencrypt

# 备份
sudo -u ostium /usr/local/bin/ostium backup create --password '...'
```

更多参考：

- [安装](../installation.md)
- [配置](../configuration.md)
- [订阅](../subscriptions.md)
- [证书](../certificates.md)
- [备份与恢复](../operations/backup-restore.md)
- [排障](../operations/troubleshooting.md)
