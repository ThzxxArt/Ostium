# API reference

Base path: `/api/v1`. OpenAPI is served at `/api/docs` (admin-only in
production) and `/api/openapi.json`.

Authentication is an HttpOnly session cookie for the browser, a loopback CLI
token, or a Bearer API token. Mutating requests require `X-CSRF-Token` matching
the `ostium_csrf` cookie unless authenticated with a Bearer token. Errors use
RFC 9457 fields plus `code` and `request_id`.

| Group | Endpoints |
|---|---|
| Auth | `GET /auth/csrf`, `GET /auth/status`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/password`, `POST /auth/totp/start|confirm|disable` |
| Setup | `POST /setup` |
| Status | `GET /healthz`, `GET /readyz` (root), `GET /system/info` |
| Inbounds | `GET /inbounds`, `PATCH /inbounds/{kind}`, `POST /inbounds/{kind}/reality-keys` |
| Users | `GET/POST /users`, `GET/PATCH/DELETE /users/{id}`, `POST /users/{id}/rotate`, `POST /users/{id}/reset-usage`, `GET /users/{id}/usage`, `GET /users/{id}/export` |
| Subscriptions | `GET /users/{id}/subscription`, `POST /users/{id}/subscription/rotate`, `GET /subscriptions`, public `GET /sub/{token}?format=...` |
| Profiles | `GET/POST /profiles`, `PATCH/DELETE /profiles/{id}`, `POST /profiles/{id}/refresh`, `GET /profiles/{id}/export`, `GET /profiles/{id}/test` |
| Rules | `GET/POST /rules`, `PATCH/DELETE /rules/{id}`, `POST /rules/reorder`, `POST /rules/test`, `GET/POST /rule-sets`, `POST /rule-sets/{id}/update`, `DELETE /rule-sets/{id}` |
| Stats | `GET /stats/overview`, `GET /stats/traffic`, `GET /stats/engine`, `GET/DELETE /connections`, `DELETE /connections/{id}` |
| Logs | `GET /logs`, `GET /logs/download` |
| Certificates | `GET/POST /certificates`, `POST /certificates/issue`, `POST /certificates/upload`, `POST /certificates/{id}/renew`, `POST /certificates/{id}/use`, `DELETE /certificates/{id}` |
| Jobs | `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel` |
| System | `POST /system/proxy`, `POST /system/tun`, `POST /system/mode`, `POST /system/connect`, `POST /system/disconnect`, `GET /system/services`, `POST /system/services/{name}/restart`, `GET /system/doctor`, `GET /system/diagnostics` |
| Backups | `GET/POST /backups`, `POST /backups/{id}/restore`, `DELETE /backups/{id}` |
| Alerts | `GET /alerts`, `POST /alerts/{id}/ack` |
| Audit | `GET /audit` |
| Settings | `GET/PATCH /settings`, `POST /settings/public-ui`, `GET/POST /api-tokens`, `DELETE /api-tokens/{id}` |
| Events | `WS /events` |

Long-running actions return `202` with a `job_id`. Poll `/jobs/{id}` or listen to
`/events` (`job.created`, `job.updated`, `engine.applied`, `alert.created`,
`stats.tick`, `quota.exceeded`). The public subscription endpoint is rate-limited
separately and never accepts an admin session.
