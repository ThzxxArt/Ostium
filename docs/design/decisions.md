# 实施决策记录

本文件记录实施过程中与 `v0.2.0-final.md` 的差异，原则仍是：服务端-only、零兼容、零迁移、成熟框架、现代 UI。

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
