# API 参考

基础路径：`/api/v1`。OpenAPI 在 `/api/docs`（需管理员会话）和 `/api/openapi.json`（同样需管理员）。
匿名访问返回 401。

认证方式：

- 浏览器：HttpOnly 会话 Cookie
- 本地 CLI：回环 token
- 自动化：`Authorization: Bearer <API token>`

除 Bearer token 外，所有写请求都需要 `X-CSRF-Token`，并与 `ostium_csrf` Cookie 匹配。错误响应使用 RFC 9457 字段，并附加 `code` 和 `request_id`。

| 分组 | 端点 |
|---|---|
| Auth | `GET /auth/csrf`、`GET /auth/status`、`POST /auth/login`、`POST /auth/logout`、`GET /auth/me`、`POST /auth/password`、`POST /auth/totp/start|confirm|disable` |
| Setup | `POST /setup` |
| Status | `GET /healthz`、`GET /readyz`（root）、`GET /system/info` |
| Inbounds | `GET /inbounds`、`PATCH /inbounds/{kind}`、`POST /inbounds/{kind}/reality-keys` |
| Users | `GET/POST /users`、`GET/PATCH/DELETE /users/{id}`、`POST /users/{id}/rotate`、`POST /users/{id}/reset-usage`、`GET /users/{id}/usage`、`GET /users/{id}/export` |
| Subscriptions | `GET /users/{id}/subscription?reveal=true`、`POST /users/{id}/subscription/rotate`、`GET /subscriptions`、公开 `GET /sub/{token}?format=...` |
| Profiles | `GET/POST /profiles`、`PATCH/DELETE /profiles/{id}`、`POST /profiles/reorder`、`POST /profiles/{id}/activate`、`POST /profiles/{id}/refresh`、`GET /profiles/{id}/export`、`GET /profiles/{id}/test` |
| Rules | `GET/POST /rules`、`PATCH/DELETE /rules/{id}`、`POST /rules/reorder`、`POST /rules/test`、`GET/POST /rule-sets`、`POST /rule-sets/{id}/update`、`DELETE /rule-sets/{id}` |
| Stats | `GET /stats/overview`、`GET /stats/traffic`、`GET /stats/engine`、`GET/DELETE /connections`、`DELETE /connections/{id}` |
| Logs | `GET /logs`、`GET /logs/download` |
| Certificates | `GET/POST /certificates`、`POST /certificates/issue`、`POST /certificates/upload`、`POST /certificates/{id}/renew`、`POST /certificates/{id}/use`、`DELETE /certificates/{id}` |
| Jobs | `GET /jobs`、`GET /jobs/{id}`、`POST /jobs/{id}/cancel` |
| System | `GET /system/info`、`GET /system/provenance`、`GET /system/port-owners`、`GET /system/dns`、`GET /system/selftest?target=google\|huggingface\|github`、`POST /system/proxy`、`POST /system/tun`、`POST /system/mode`、`POST /system/connect`、`POST /system/disconnect`、`GET /system/services`、`POST /system/services/{name}/restart`、`GET /system/doctor`、`GET /system/diagnostics`、`GET /system/diagnostics/download` |
| Backups | `GET/POST /backups`、`POST /backups/{id}/restore`、`DELETE /backups/{id}` |
| Alerts | `GET /alerts`、`POST /alerts/{id}/ack` |
| Audit | `GET /audit` |
| Settings | `GET/PATCH /settings`、`POST /settings/public-ui`、`GET/POST /api-tokens`、`DELETE /api-tokens/{id}` |
| Events | `WS /events` |

长任务返回 `202` 和 `job_id`。轮询 `/jobs/{id}`，或监听 `/events`：`job.created`、`job.updated`、`engine.applied`、`alert.created`、`stats.tick`、`quota.exceeded`。

`GET /users/{id}/subscription` 默认只返回 `reveal_required`/`token_hint`；完整 token、URL 和
二维码需 `?reveal=true`，并写审计。未知订阅格式返回 400；禁用/到期/超配额返回 403。

公开订阅端点是独立限速的，永远不接受管理员会话。

## 版本、诊断与 DNS（0.1.11）

- `GET /system/provenance`：控制面版本/commit/executable/PID、核心版本、Web `build.json`、
  监听端口 PID/路径/启动时间，以及 `consistency`。版本响应均带 `Cache-Control: no-store`。
- `GET /system/port-owners`：控制面、混合代理和核心端口的实际监听进程。
- `GET /system/dns`：配置模式、实际模式、最近 DoH 探测结果和 `last-good.meta.json`。
- `GET /system/selftest?target=google|huggingface|github`：返回 `stage`
  （dns/tcp/tls/http）、`latency_ms`、`status_code` 和错误。
- `GET /system/doctor`：返回带 `data` 和 `duration_ms` 的分类检查。
- `GET /system/diagnostics/download`：tar.gz 内含 `ostium-diagnostics.json`、
  `provenance.json`、`dns.json`、`ports.json`、`checks.json`，全部脱敏且 `no-store`。
- `/stats/overview` 增加 `online_window_seconds`、`rates_stale` 和 `rates.stale`；
  `/users` 返回 `online_window_seconds`、`last_traffic_at` 与 `online_reason`。
