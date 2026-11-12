# Upgrade and rollback

## Application

1. Read the release notes and back up first.
2. `ostium update --check`; download the signed release manually.
3. Server: stop `ostium.service` only. The core keeps the tunnel alive.
4. Install the new wheel into `/opt/ostium/venv`.
5. Run migrations (`ostium serve` applies them at startup).
6. Start the UI and check `/readyz`.
7. Roll back the wheel and database backup if the health check fails.

Never run a silent auto-update. The UI exposes a download link, not an
auto-executor.

## Core

The core version is pinned in the manifest. `ostium core install` verifies the
SHA256, then the supervisor runs `sing-box check` against the current
configuration before switching. If the check fails, the previous binary and
configuration remain active.

## Database

SQLite migrations are forward-only in v0.1.0. Release notes mark any migration
that cannot be rolled back; take a backup before upgrading. Alembic tracks the
schema version in `alembic_version`.

## Client

Desktop installers replace the app and services in place. The core restarts
briefly; the UI is unavailable for a few seconds. Data and profiles are
preserved.
