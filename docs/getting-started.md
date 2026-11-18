# 快速开始（开发）

## 前置

- Linux（推荐 Debian 13 / Ubuntu 24.04+）
- Python 3.14（由 `uv` 管理）
- Git、curl、OpenSSL

## 启动

```bash
git clone https://github.com/ThzxxArt/Ostium.git
cd ostium
uv sync --extra dev
uv run ostium migrate
uv run ostium init --username admin --password 'Change-This-Password-2026'
uv run ostium web
```

打开 <http://127.0.0.1:8000/>，使用 `admin` 和刚设置的密码登录。
首次登录会要求修改密码。

`ostium init` 默认创建四条线路记录，并启用 VLESS Reality（端口 443）。
没有 root 权限时，临时改端口：

```bash
uv run ostium inbound set-port vless 8443
uv run ostium apply
```

## 启动数据面

开发时用前台进程观察日志：

```bash
uv run ostium worker
```

worker 会生成配置、执行 `sing-box check`、启动 sing-box，并监听：

- `443/tcp`（VLESS/Trojan）
- `443/udp`（Hysteria2）
- `8388/tcp`（Shadowsocks，默认未启用）
- `127.0.0.1:19090`（Clash API）
- `127.0.0.1:19091`（V2Ray stats）

需要真实 sing-box 二进制。构建 pinned 版本：

```bash
bash scripts/build-core.sh
cp dist/sing-box .cache/bin/sing-box
```

官方 release 二进制不包含 `with_v2ray_api`，统计会不可用；必须使用本项目构建标签。

## 创建第一个用户

```bash
uv run ostium user add alice --quota 100G --cycle monthly
uv run ostium user subscription alice --reveal
```

把 Base64 链接导入 v2rayN / Shadowrocket；Clash 链接加 `/clash` 后缀。

## 开发检查

```bash
uv run pytest
uv run pytest tests/contract      # 需要真实 sing-box / mihomo
uv run ruff check src tests
uv run python manage.py check
```

## 数据目录

默认 `./var/`。可用 `OSTIUM_DATA_DIR` 指向其他目录。

```text
var/
  ostium.db
  certs/
  runtime/{config.json,usage.json,clash.secret,worker.lock}
  logs/{ostium.log,sing-box.log}
  backups/
```
