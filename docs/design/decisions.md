# 实施决策记录

本文件记录实施过程中与 `v0.2.0-final.md` 的差异，原则仍是：服务端-only、零兼容、零迁移、成熟框架、现代 UI。

## PyPI 包名沿用 `ostium-ctl`

0.2.0 产品名仍是 Ostium Server，但 Python 发行包名最终沿用 0.1.x 的
`ostium-ctl`。原因是 PyPI trusted publisher 已绑定该项目的 `release.yml`
与 `pypi` environment；继续使用同名项目可以复用现有发布链路。模块、命令和
wheel 内代码仍是 `ostium`。

`ostium-server` 仅作为产品/备份格式/Docker 镜像名保留，不再作为 Python
发行包名。

## Python 3.14.5 而非 3.14.10

截至实施日，python.org / uv 可获取的最新 CPython 3.14 是 **3.14.5**；3.14.10 尚未发布。
项目锁定 `>=3.14,<3.15`，开发与 CI 使用 3.14.5。后续补丁版本可直接升级。

## `prometheus-client` 替代 `django-prometheus`

`django-prometheus 2.5.0` 的依赖声明要求 Django `<6.1`，无法与 Django 6.1.3 共存。
改用官方 `prometheus-client` 0.24.1，在 `/metrics` 中手工暴露：

- `ostium_worker_alive`
- `ostium_singbox_running`
- `ostium_active_users`
- `ostium_online_users`
- `ostium_unacknowledged_alerts`
- `ostium_disk_free_bytes`

## Alpine CSP 构建

为保持严格 CSP（无 `unsafe-eval`），使用 `@alpinejs/csp` 3.17.5 而非普通 CDN 构建。
组件通过带 nonce 的内联脚本调用 `Alpine.data()` 注册，表达式只使用属性/方法名。

## sing-box 构建

官方 release 二进制不包含 `with_v2ray_api`，统计不可用。发布与契约测试从上游
`v1.14.4` 源码构建：

```text
with_quic,with_utls,with_clash_api,with_v2ray_api,badlinkname,tfogo_checklinkname0
```

不修改上游源码，仅选择官方构建标签。

## django-health-check 4.11

4.11 不再提供 `health_check.db/cache/storage` 插件应用。使用 `HealthCheckView`
子类，在 `/health/` 暴露数据库、缓存、存储检查；`/healthz`、`/readyz` 仍为项目自有视图。

## 本地 E2E 端口

开发主机普通用户无法绑定 443，本地 E2E 使用 8443 并记录在
[`docs/operations/e2e-evidence.md`](../operations/e2e-evidence.md)。
生产 systemd/Compose 通过 `CAP_NET_BIND_SERVICE` 绑定 443。

## 任务取消

django-q2 没有运行中任务取消 API。`/jobs/{id}/cancel` 对已开始任务返回 409；
队列中的 `OrmQ` 消息可被移除。UI 明确提示“已开始的任务无法取消”。

## 订阅 Profile-Title 编码

非 ASCII 用户名会使 HTTP header 无法用 latin-1 编码；订阅视图对非 ASCII 标题使用
客户端约定的 `base64:` 前缀，而不是 percent-encoding，保证客户端能显示正确的
中文标题。

## Django Admin 的 CSP 例外

Aurora 控制台使用 Alpine CSP build，保持 `script-src 'self' 'nonce-…'`，不启用
`unsafe-eval`。Django Admin + Unfold 自带标准 Alpine build，必须使用
`unsafe-eval` 才能正常渲染遮罩、下拉和快捷键面板。为避免破坏 Admin，CSP 仅在
`/admin/` 路径追加 `'unsafe-eval' 'unsafe-inline'`；控制台和订阅路径不受影响。
这是单管理员、内部管理面的明确权衡，已记录在安全文档。

## 备份恢复的字段密钥

备份 manifest 保存创建时的字段密钥。恢复时如果主机的
`OSTIUM_FIELD_KEY` 不同，会在 loaddata 后用备份密钥解密、再用当前密钥重新
加密所有凭据，保证备份可跨主机恢复，不需要手工改环境变量。

## Docker 下的 Clash API

默认 Clash API 仍绑定 `127.0.0.1:19090`。Compose 中 web 与 worker 分容器，
因此 worker 通过 `OSTIUM_CLASH_BIND=0.0.0.0:19090` 在内部网络监听，web 通过
`OSTIUM_CLASH_URL=http://worker:19090` 访问；secret 仍由共享 runtime 卷提供。

## 统计方向计数

`ProxyUser` 增加 `uploaded_bytes` / `downloaded_bytes`，与 `used_bytes` 一起
在 flush 时原子累加，并在月度/手动重置时归零。`Subscription-Userinfo` 使用这
三个权威计数，不再用可能被保留期删除的 `TrafficDaily` 反推。

## 发布 workflow 默认只构建

`release.yml` 的 `publish_pypi` 默认改为 `false`。手动运行 workflow 时默认只
构建、校验并上传 GitHub Actions artifact；确认要发布时才显式设为 `true`。
PyPI 版本不可覆盖，这样避免误点一次就产生不可撤回的发行版。

## 容器基础镜像按 digest 固定

Dockerfile 与 Compose 的 Python、Go、Debian、Caddy、PostgreSQL、uv 基础镜像
均使用 `@sha256:` digest 固定；CI 的 PostgreSQL service 也使用同一 digest。
这样 tag 被上游移动时不会静默改变发布内容。

## Docker 构建路径

Dockerfile 的 CSS 阶段改为在 `uv sync` 之后的最终依赖环境中运行 Tailwind。
这样 Tailwind 同时扫描项目模板和 `.venv` 中的 Unfold 管理模板；此前把
`app.css` 平铺到独立目录会让 `@source` 失效并静默丢掉管理端工具类。Docker
构建上下文只保留 `docs/pypi-readme.md`，因为 `pyproject.toml` 的 readme
指向它，而其余文档不必进入镜像。

## 备份快照包含 contenttypes 与权限

备份和恢复前的安全快照都包含 `contenttypes` 与 `auth.permission`，并在
restore 的 `flush` 中使用 `inhibit_post_migrate`。否则 `auditlog` 的外键会
指向重新生成后 ID 不同的 content type，导致备份无法恢复。恢复失败时会用
flush 前的安全快照回滚，避免留下空数据库。

## 安装器默认使用 release 资产

`install.sh` 默认下载 GitHub Release 的 wheel、sdist、预构建 sing-box 和
`SHA256SUMS`，校验后安装；源码下载与 sing-box 编译只在 `--from-source` 时
使用。这样发布资产和线上安装保持一致，也避免每次安装都依赖 Go 工具链。
`--version` 用于固定 release 版本，`--ref` 仅用于源码模式。

## 静态源文件不参与 collectstatic

Tailwind 源文件移到 `src/ostium/static_src/app.css`，不放在 `static/` 下；
同时移除 vendored Chart.js 的 `sourceMappingURL`。生产
`CompressedManifestStaticFilesStorage` 不再因缺少 source map 或把
`@import "tailwindcss"` 当静态 URL 而失败。CI 增加真实 manifest storage 的
collectstatic 回归测试。

## 订阅的 Referrer-Policy 作用域

Caddy 只对非 `/sub/*` 响应设置 `Referrer-Policy: same-origin`，避免覆盖
Django 在订阅响应上设置的 `no-referrer`。控制台仍使用 `same-origin` 以
保证表单 POST 的 Origin 头正常。

## 侧栏与移动端底部边界

侧栏本身仍是 `position: sticky; height: 100vh`，但 `.app-shell::before` 会在
整个文档高度上绘制左侧背景与边框，避免长页面/全页截图在视口下方出现断开的
左栏。移动端底栏改为贴住视口底部，并预留
`env(safe-area-inset-bottom)`；内容底部 padding 随底栏高度增加，滚动到底时
最后一个内容块不会被底栏遮挡。

## readiness 状态码与告警恢复

`/readyz` 在 worker/sing-box 未就绪时返回 503，而不是 200。worker 在统计、
证书、DNS 回退、自动备份和二进制校验恢复后显式 resolve 对应告警，避免已经
恢复的条件永久停留在告警列表。
