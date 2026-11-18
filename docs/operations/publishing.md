# PyPI 发布

Ostium Server 的 Python 包名是 `ostium-server`，命令是 `ostium`。

## 这个包包含什么

PyPI wheel 包含：

- Django 应用、迁移、模板、静态 CSS/JS/字体/图标；
- `ostium` 命令行入口；
- PyPI 长描述 `README.md`。

PyPI wheel **不包含**：

- systemd unit、Caddyfile、certbot hooks、Dockerfile/Compose；
- 生产数据目录、证书、备份。

所以：

- 只想在 Python 项目里使用 `ostium` 命令：可以 `pip install ostium-server`。
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
unzip -l dist/ostium_server-0.2.0-py3-none-any.whl | head
```

## 方式一：GitHub Actions 可信发布

发布入口统一在 **`release.yml`**，不再使用单独的 `pypi.yml`。

1. 在 PyPI 创建项目 `ostium-server`（或配置 pending trusted publisher）。
2. 在 PyPI 的 Publishing 设置中添加 trusted publisher：
   - owner：`ThzxxArt`
   - repository：`Ostium`
   - workflow：`release.yml`
   - environment：`pypi`
3. 在 GitHub 仓库创建 `pypi` environment（可加审批）。
4. 手动运行 workflow：

```text
Actions -> release -> Run workflow
  version: 0.2.0
  publish_pypi: true
```

`publish_pypi=false` 时只构建并上传 GitHub Actions artifact，不访问 PyPI。

> **重要：** 0.1.x 发布的是 `ostium-ctl`，0.2.0 的包名是
> `ostium-server`。PyPI 的 trusted publisher 是按“项目名 + workflow +
> environment”绑定的；只给旧的 `ostium-ctl` 配置 `release.yml` 不会授权
> 新的 `ostium-server`。需要在 PyPI 为 `ostium-server` 单独添加
> trusted publisher（pending publisher 也可以），或者改用 API token。
>
> 如果确实希望继续用 `ostium-ctl` 这个名字，需要同时修改 `pyproject.toml`
> 的 `name` 和所有发布文档，这会偏离 0.2.0 的包名决策，需单独确认。

## 方式二：本地发布

```bash
uv build
UV_PUBLISH_TOKEN=... uv publish
```

不要把 token 写入仓库、脚本或 README。

## 安装验证

发布后：

```bash
python -m venv /tmp/ostium-pypi
/tmp/ostium-pypi/bin/pip install ostium-server==0.2.0
OSTIUM_DEBUG=1 OSTIUM_DATA_DIR=/tmp/ostium-pypi-data \
  /tmp/ostium-pypi/bin/ostium help
```

完整服务端仍建议使用一键安装器，因为 PyPI 包不包含 systemd/Caddy/Docker
部署资产。

## 为什么之前没有 PyPI 发布物

0.2.0 验收阶段明确要求“不发布 PyPI/GHCR/GitHub Release、不打新 tag”，
因此仓库只有可构建的 wheel/sdist，没有实际上架。现在发布入口已并入
`release.yml`；真正上架需要在 PyPI 为 `ostium-server` 配置 trusted
publisher 或提供 token 后手动触发。旧项目 `ostium-ctl` 的 trusted
publisher 不会自动授权新项目名。
