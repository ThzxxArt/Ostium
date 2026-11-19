# PyPI 发布

Ostium Server 的 Python 包名沿用 0.1.x 的 **`ostium-ctl`**，命令仍是 `ostium`。

这样可以直接复用已有的 PyPI 项目和 `release.yml` trusted publisher，
不需要为 0.2.x 新建项目名。

## 0.2.6 发布记录

2026-11-19 已完成全量发布：

- PyPI：https://pypi.org/project/ostium-ctl/0.2.6/
- GHCR：`ghcr.io/thzxxart/ostium-server:0.2.6` / `:latest`
- GitHub Release：https://github.com/ThzxxArt/Ostium/releases/tag/v0.2.6
- tag：`v0.2.6`

本版修复证书链路：安装/升级自动导入已有 certbot 证书；线路页可直接选择；
证书导入支持上传文件、选择服务器暂存目录、粘贴 PEM。

## 0.2.5 发布记录

2026-11-19 已完成全量发布：

- PyPI：https://pypi.org/project/ostium-ctl/0.2.5/
- GHCR：`ghcr.io/thzxxart/ostium-server:0.2.5` / `:latest`
- GitHub Release：https://github.com/ThzxxArt/Ostium/releases/tag/v0.2.5
- tag：`v0.2.5`

本版修复控制台设置字段渲染、证书导入页、系统配置状态说明、API 文档 CSP、
Django Admin 中文分组和用户配额显示。

## 0.2.4 发布记录

2026-11-19 已完成全量发布：

- PyPI：https://pypi.org/project/ostium-ctl/0.2.4/
- GHCR：`ghcr.io/thzxxart/ostium-server:0.2.4` / `:latest`
- GitHub Release：https://github.com/ThzxxArt/Ostium/releases/tag/v0.2.4
- tag：`v0.2.4`

本版修复生产 settings 的 `SECURE_REDIRECT_EXEMPT` 去掉前导斜杠，使
`/healthz`、`/readyz`、`/metrics` 不再被 301 重定向。

## 0.2.3 发布记录

2026-11-19 已完成全量发布：

- PyPI：https://pypi.org/project/ostium-ctl/0.2.3/
- GHCR：`ghcr.io/thzxxart/ostium-server:0.2.3` / `:latest`
- GitHub Release：https://github.com/ThzxxArt/Ostium/releases/tag/v0.2.3
- tag：`v0.2.3`

本版修复 systemd 下 `ostium web` 找不到 venv 内 gunicorn 的问题。

## 0.2.2 发布记录

2026-11-19 已完成全量发布：

- PyPI：https://pypi.org/project/ostium-ctl/0.2.2/
- GHCR：`ghcr.io/thzxxart/ostium-server:0.2.2` / `:latest`
- GitHub Release：https://github.com/ThzxxArt/Ostium/releases/tag/v0.2.2
- tag：`v0.2.2`

本版修复：安装器默认使用 release 资产（wheel + sdist + prebuilt sing-box），
不再默认源码构建；同时移除 Chart.js source map 引用并修复生产 `collectstatic`。

## 0.2.1 发布记录

2026-11-18 已完成全量发布：

- PyPI：https://pypi.org/project/ostium-ctl/0.2.1/
- GHCR：`ghcr.io/thzxxart/ostium-server:0.2.1` / `:latest`
- GitHub Release：https://github.com/ThzxxArt/Ostium/releases/tag/v0.2.1
- tag：`v0.2.1`

## 0.2.0 发布记录

2026-11-18 已完成全量发布：

- PyPI：https://pypi.org/project/ostium-ctl/0.2.0/
- GHCR：`ghcr.io/thzxxart/ostium-server:0.2.0` / `:latest`
- GitHub Release：https://github.com/ThzxxArt/Ostium/releases/tag/v0.2.0
- tag：`v0.2.0`

## 这个包包含什么

PyPI wheel 包含：

- Django 应用、迁移、模板、静态 CSS/JS/字体/图标；
- `ostium` 命令行入口；
- PyPI 长描述 `docs/pypi-readme.md`。

PyPI wheel **不包含**：

- systemd unit、Caddyfile、certbot hooks、Dockerfile/Compose；
- 生产数据目录、证书、备份。

所以：

- 只想在 Python 项目里使用 `ostium` 命令：可以 `pip install ostium-ctl==0.2.6`。
- 要部署完整服务端：使用 [一键在线安装](../tutorials/from-zero.md) 或源码
  `install.sh`，它会同时安装部署资产。

## 发布前检查

```bash
uv sync --frozen --extra dev
uv run pytest -q
uv run mkdocs build --strict
uv build
```

检查 wheel：

```bash
unzip -l dist/ostium_ctl-0.2.6-py3-none-any.whl | head
```

## GitHub Actions 可信发布

发布入口是 **`release.yml`**，不再使用单独的 `pypi.yml`。已有的 PyPI
trusted publisher 应保持：

```text
project:     ostium-ctl
owner:       ThzxxArt
repository:  Ostium
workflow:    release.yml
environment: pypi
```

如果 PyPI 上还没有为 `ostium-ctl` 配置这个 workflow，请在 PyPI 项目的
Publishing 设置中补上；GitHub 仓库的 `pypi` environment 已经存在。

手动运行：

```text
Actions -> release -> Run workflow
  version: 0.2.6
  publish_pypi: true
```

`publish_pypi` 默认是 **false**：默认只构建、校验并上传 GitHub Actions
artifact，不访问 PyPI。确认要发布时才显式设为 `true`；PyPI 版本不可覆盖，
所以不要把它当作普通的重跑按钮。

发布 job 会先运行
`uv run python scripts/verify-package.py dist`，确认 wheel 的发行名是
`ostium-ctl`、版本与 `VERSION` 一致，并包含模板、静态资源和迁移。

## 本地发布

```bash
uv build
UV_PUBLISH_TOKEN=... uv publish
```

不要把 token 写入仓库、脚本或 README。

## 安装验证

发布后：

```bash
python -m venv /tmp/ostium-pypi
/tmp/ostium-pypi/bin/pip install ostium-ctl==0.2.6
OSTIUM_DEBUG=1 OSTIUM_DATA_DIR=/tmp/ostium-pypi-data \
  /tmp/ostium-pypi/bin/ostium help
```

完整服务端仍建议使用一键安装器，因为 PyPI 包不包含 systemd/Caddy/Docker
部署资产。

## 与 0.1.x 的关系

- PyPI 项目名不变：`ostium-ctl`。
- 0.2.x 是服务端-only 重写，不再包含桌面客户端、TUN、SPA。
- 0.1.x 数据、配置、订阅 token 不迁移。
- 旧版本仍可通过 PyPI 历史版本或 `v0.1.12` tag 获取，但不应与新版本混用。
