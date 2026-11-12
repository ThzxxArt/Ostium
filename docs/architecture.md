# Architecture

Ostium uses two services so the privileged network path is separate from the
Web/API/database path.

```text
systemd / launchd / SCM
├─ ostium-core.service
│   ├─ ostium core-run
│   └─ sing-box (child, pinned 1.14.4 + with_v2ray_api)
└─ ostium.service
    ├─ uvicorn (FastAPI + SPA)
    └─ background tasks (stats, ACME, jobs, backups)
```

## Control plane (`ostium.service`)

FastAPI, Vue SPA, CLI, SQLite/Alembic, users, subscriptions, rules,
certificates, ACME, backups, audit and the job system. It never binds the
public proxy ports and never creates a TUN device. On a client it runs as the
logged-in user; on a server as the `ostium` system user.

## Core (`ostium-core.service`)

A small FastAPI app on `127.0.0.1:8788` with a bearer token. It accepts a
whitelisted sing-box configuration, validates it against the role policy, writes
`last-good.json`, runs `sing-box check`, atomically replaces the runtime config
and reloads via SIGHUP (restart on Windows). It never executes a shell and
never connects to the database.

## Data flow

```text
client app → 127.0.0.1:7890 (mixed) / TUN
           → VLESS+Reality / Hysteria2 / Trojan / SS2022
           → server sing-box → direct egress
```

The control plane pushes generated JSON to the core API. The core API applies it
transactionally: a failed check or start keeps the previous configuration.
Statistics are read from sing-box's V2Ray gRPC API every 5 seconds and flushed
to SQLite every minute. Quotas and expiry are enforced by the control plane; if
it is stopped, the core continues serving existing configuration and quota
enforcement pauses (documented limitation).

## Ports

| Component | Address |
|---|---|
| Server proxy | `0.0.0.0:443/tcp` Reality/Trojan |
| Server Hysteria2 | `0.0.0.0:443/udp` |
| Server SS2022 | `0.0.0.0:8388/tcp+udp` (off by default) |
| Server UI | `127.0.0.1:8443` default; public only with TLS+TOTP |
| ACME HTTP-01 | `0.0.0.0:80/tcp` during issuance |
| Client mixed | `127.0.0.1:7890` |
| Client UI | `127.0.0.1:8787` |
| Core API | `127.0.0.1:8788` |
| Clash API | `127.0.0.1:19090` |
| V2Ray stats | `127.0.0.1:19091` |

## Files

Server data lives in `/var/lib/ostium`, configuration in `/etc/ostium`.
Client UI data lives in the platform user data directory; the client core uses
`/var/lib/ostium-core` on Linux. Secrets (`master.key`, `core.token`,
`clash.secret`) are mode 0600/0640 and never committed.

## Database

SQLite with WAL, foreign keys and Alembic. The initial schema is created
automatically and stamped with the initial migration; subsequent upgrades run
Alembic migrations. Sensitive fields use AES-256-GCM with AAD bound to
table/row/field.
