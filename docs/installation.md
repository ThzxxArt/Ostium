# 安装

生产环境支持两种方式：systemd 或 Docker Compose。二者都只面向 Linux。

> 第一次部署建议直接看 [从零部署中文教程](tutorials/from-zero.md)：
> 从 DNS、防火墙、Caddy/certbot、首次登录、建用户、订阅到续期和排障逐步执行。

## 方式一：systemd

### 要求

- root 权限、systemd
- Debian 13 / Ubuntu 24.04 或相近发行版
- 一个指向服务器的域名（可选，但公网管理面需要）
- 入站 443/tcp、443/udp；管理面 8443/tcp（若使用 Caddy）

### 一键在线安装

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

不需要手动下载脚本；安装器会自动下载源码和部署资产。也可以 clone 后执行：

```bash
sudo bash install.sh --domain vpn.example.com --with-caddy
```

安装器会：

1. 安装 `ca-certificates`、`curl`、`openssl`、`git`（certbot/Caddy 需预先安装）。
2. 下载静态 `uv`，在 `/opt/ostium/python` 安装 Python 3.14，创建 `/opt/ostium/venv`。
3. 安装本仓库（或 `--wheel` 指定的 wheel）。
4. 从固定的 sing-box `v1.14.4` 源码构建带
   `with_v2ray_api,with_clash_api,with_quic,with_utls` 的数据面二进制；
   如果系统没有 Go，会自动下载固定版本的 Go 工具链。
5. 创建 `ostium` 用户与 `/var/lib/ostium`、`/etc/ostium`。
6. 生成 `OSTIUM_SECRET_KEY`、`OSTIUM_FIELD_KEY` 和 `/etc/ostium/ostium.env`，
   并把构建出的 sing-box SHA256 写入运行期校验变量。
7. 执行 migrate、collectstatic、init，打印一次性管理员密码。
8. 安装并启用 `ostium-web`、`ostium-worker`、`ostium-jobs`。
9. 可选：申请证书、复制到 `/etc/ostium/tls`、配置 Caddy 8443；certbot
   standalone 续期前后会自动停止/启动 Caddy，deploy hook 会把证书同步进 Ostium。

不使用 Caddy 时，通过 SSH 隧道访问：

```bash
ssh -L 8000:127.0.0.1:8000 user@server
# 浏览器打开 http://127.0.0.1:8000/
```

### 目录

```text
/opt/ostium/venv/                Python 环境
/opt/ostium/core/sing-box        固定数据面二进制
/etc/ostium/ostium.env           环境变量（0640 root:ostium）
/var/lib/ostium/                 数据库、证书、运行时、日志、备份
```

### 升级

在线升级不需要本地 checkout：

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --ref main
```

或从本地 checkout 升级：

```bash
sudo bash install.sh upgrade --from-source
```

升级前请先创建备份（见 [备份与恢复](operations/backup-restore.md)）。
升级会重启 web/worker/jobs，隧道可能中断 1–3 秒。

### 卸载

```bash
sudo bash install.sh uninstall           # 保留数据
sudo bash install.sh uninstall --purge   # 删除数据与用户
```

## 方式二：Docker Compose

```bash
cd deploy/docker
cp ostium.env.example ostium.env
# 编辑 ostium.env：两个 32 字节密钥、域名、ALLOWED_HOSTS
openssl rand -base64 32   # OSTIUM_FIELD_KEY
openssl rand -hex 32      # OSTIUM_SECRET_KEY

docker compose pull
docker compose up -d
```

镜像：`ghcr.io/thzxxart/ostium-server:0.2.1`。需要本地构建时使用
`docker compose up -d --build`。

使用 Caddy profile 时，需要先把证书复制到宿主机 `/etc/ostium/tls/<domain>/`；
Compose 会把它以只读方式挂载进 Caddy 容器。没有证书时不要启用 caddy profile。

服务：

| 服务 | 作用 | 端口 |
|---|---|---|
| web | Gunicorn + Django | 内部 8000 |
| worker | sing-box 监督 | 443/tcp、443/udp、8388/tcp |
| jobs | django-q2 | 无 |
| caddy（profile） | TLS 反代 | 80、8443 |
| postgres（profile） | PostgreSQL 18 | 内部 5432 |

首次启动后运行一次初始化：

```bash
docker compose exec web ostium init --username admin
```

SQLite 数据必须放在本机卷，不要放 NFS。高并发或多写入场景使用 PostgreSQL：

```bash
# deploy/docker/ostium.env
OSTIUM_DB_URL=postgres://ostium:secret@postgres:5432/ostium
POSTGRES_PASSWORD=secret
docker compose --profile postgres up -d
```

`ostium.env` 通过 Compose 的 `env_file` 注入；`POSTGRES_PASSWORD` 必须在
shell 环境或项目 `.env` 中提供。首次切换 Postgres 时先启动 postgres，
等健康检查通过后再启动 web/worker。

## PyPI 包

`ostium-ctl` 也可以作为 Python 包发布（沿用 0.1.x 的 PyPI 项目名），但
PyPI wheel 只包含代码、模板和静态资源，不包含 systemd/Caddy/Docker 部署
资产。完整服务端请使用上面的一键在线安装器。发布流程见
[PyPI 发布](operations/publishing.md)。

## 安装后检查

```bash
ostium doctor
ostium status
curl -fsS http://127.0.0.1:8000/healthz
```

公网暴露前务必：

1. 登录并启用 TOTP。
2. 设置 `OSTIUM_REQUIRE_TOTP=true`。
3. 使用 Caddy TLS 或可信反向代理。
4. 设置 `OSTIUM_ALLOWED_HOSTS` 与 `OSTIUM_CSRF_TRUSTED_ORIGINS`。
5. 运行 `ostium doctor`，确认没有 fail。
