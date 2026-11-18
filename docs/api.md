# API

基础路径：`/api/v1`。认证：

```http
Authorization: Api-Key <key>
```

API key 只显示一次；scope 为 `read` 或 `write`。创建：

```bash
ostium token create ci --scope read --expires 90
```

## 端点

| 分组 | 端点 |
|---|---|
| Health | `GET /healthz`、`/readyz`、`/metrics`（无需 key） |
| Users | `GET/POST /users`、`GET/PATCH/DELETE /users/{id}` |
| User actions | `POST /users/{id}/rotate`、`/reset-usage`、`GET /usage` |
| Subscriptions | `GET /users/{id}/subscription`、`POST .../subscription/reveal`、`POST .../subscription/rotate` |
| Inbounds | `GET /inbounds`、`GET/PATCH /inbounds/{kind}`、`POST /inbounds/{kind}/reality-keys` |
| Certificates | `GET /certificates`、`POST /certificates`、`POST /certificates/{id}/assign`、`DELETE` |
| Stats | `GET /stats/overview`、`GET /stats/traffic?days=7` |
| Connections | `GET/DELETE /connections`、`DELETE /connections/{id}` |
| Jobs | `GET /jobs`、`GET /jobs/{id}`、`POST /jobs/{id}/cancel` |
| Backups | `GET/POST /backups`、`POST /backups/{id}/restore`、`DELETE` |
| Alerts | `GET /alerts`、`POST /alerts/{id}/ack` |
| Audit | `GET /audit?action=&actor=` |
| Settings | `GET/PATCH /settings` |
| OpenAPI | `/api/schema`、`/api/docs`（docs 需要管理员登录） |

分页：`?page=`，默认 50，最大 500。
写操作需要 `write` key；读操作接受 `read` key。

## 错误格式

RFC 9457 + `code` + `request_id`：

```json
{
  "type": "about:blank",
  "title": "Request validation failed",
  "status": 400,
  "detail": {"name": ["Name must not be blank."]},
  "code": "validation_error",
  "request_id": "9f..."
}
```

## 示例

```bash
export OSTIUM_API_KEY=...

curl -s -H "Authorization: Api-Key $OSTIUM_API_KEY" \
  http://127.0.0.1:8000/api/v1/users

curl -s -X POST -H "Authorization: Api-Key $OSTIUM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"alice","quota_bytes":107374182400,"quota_cycle":"monthly"}' \
  http://127.0.0.1:8000/api/v1/users

curl -s -X POST -H "Authorization: Api-Key $OSTIUM_API_KEY" \
  http://127.0.0.1:8000/api/v1/users/<uuid>/subscription/reveal
```

## 限速

- 匿名：30/min
- 用户：240/min
- 订阅：IP 60/min，token 120/min

超限返回 429；订阅带 `Retry-After`。
