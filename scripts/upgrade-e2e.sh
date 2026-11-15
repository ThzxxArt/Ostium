#!/usr/bin/env bash
# Exercise a real installed 0.1.3 -> current wheel upgrade without systemd.
#
# The installer upgrades the same files this script does: a fresh virtualenv,
# the published previous wheel, then the locally built wheel.  It verifies that
# the database migrates, users and the master key survive, and that an encrypted
# backup taken by the previous release can still be restored.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
FROM_VERSION="${OSTIUM_E2E_FROM_VERSION:-0.1.3}"
WORK="${OSTIUM_E2E_DIR:-$(mktemp -d -t ostium-upgrade-XXXXXX)}"
KEEP="${OSTIUM_E2E_KEEP:-false}"

say() { echo "[upgrade-e2e] $*"; }
fail() { echo "[upgrade-e2e] error: $*" >&2; exit 1; }

cleanup() {
  if [[ "$KEEP" != "true" ]]; then
    rm -rf "$WORK"
  else
    say "keeping work directory: $WORK"
  fi
}
trap cleanup EXIT

command -v uv >/dev/null 2>&1 || fail "uv is required"

DATA="$WORK/data"
CONFIG="$WORK/config"
STATE="$WORK/state"
export OSTIUM_ROLE=server
export OSTIUM_DATA_DIR="$DATA"
export OSTIUM_CONFIG_DIR="$CONFIG"
export OSTIUM_STATE_DIR="$STATE"
export OSTIUM_DEV=1
export OSTIUM_HOST=127.0.0.1
export OSTIUM_PORT=28443

say "installing published ostium-ctl==$FROM_VERSION"
uv venv --python 3.13 "$WORK/old" >/dev/null
uv pip install --python "$WORK/old/bin/python" "ostium-ctl==$FROM_VERSION" >/dev/null

set +e
"$WORK/old/bin/ostium" init --role server --no-input \
  --password 'verysecret123' --domain vpn.example.com >/dev/null
init_rc=$?
set -e
# Exit 3 means "configuration saved but the core token/service is absent";
# that is the expected developer-checkout state, not an upgrade failure.
[[ "$init_rc" -eq 0 || "$init_rc" -eq 3 ]] || fail "previous init exited $init_rc"
[[ -f "$DATA/ostium.db" ]] || fail "previous init did not create a database"

set +e
"$WORK/old/bin/ostium" user add alice --quota 1G --note 'upgrade fixture' --json \
  > "$WORK/old-user.json"
user_rc=$?
set -e
[[ "$user_rc" -eq 0 || "$user_rc" -eq 3 ]] || fail "previous user add exited $user_rc"
grep -q '"user": "alice"' "$WORK/old-user.json" || fail "previous user creation failed"
"$WORK/old/bin/ostium" backup create --password 'backup-passphrase' \
  --output "$WORK/from-previous.ostb" >/dev/null

OLD_KEY="$(sha256sum "$DATA/master.key" | awk '{print $1}')"
OLD_TOKEN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["token"])' "$WORK/old-user.json")"

say "building $VERSION wheel"
mkdir -p "$WORK/dist"
SETUPTOOLS_SCM_PRETEND_VERSION="v$VERSION" uv build --wheel --out-dir "$WORK/dist" "$ROOT" >/dev/null
WHEEL="$(find "$WORK/dist" -maxdepth 1 -name 'ostium_ctl-*.whl' | head -1)"
[[ -n "$WHEEL" ]] || fail "wheel was not built"

say "installing $VERSION over 0.1.1"
uv venv --python 3.13 "$WORK/new" >/dev/null
uv pip install --python "$WORK/new/bin/python" "$WHEEL" >/dev/null

REPORTED="$("$WORK/new/bin/ostium" version 2>/dev/null | sed -n '1p')"
[[ "$REPORTED" == *"$VERSION"* ]] || fail "new CLI reports '$REPORTED', expected $VERSION"

# Opening the database runs the real Alembic upgrade path.
"$WORK/new/bin/ostium" user list --json > "$WORK/new-users.json"
grep -q '"alice"' "$WORK/new-users.json" || fail "user alice was lost during upgrade"

NEW_KEY="$(sha256sum "$DATA/master.key" | awk '{print $1}')"
[[ "$OLD_KEY" == "$NEW_KEY" ]] || fail "master.key changed during upgrade"

python3 - "$DATA/ostium.db" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
if integrity.lower() != "ok":
    raise SystemExit(f"integrity_check failed: {integrity}")
version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
if not version:
    raise SystemExit("alembic_version is empty")
print(f"database integrity ok, alembic revision {version[0]}")
PY

say "restoring the previous-release backup with current code"
"$WORK/new/bin/ostium" backup restore "$WORK/from-previous.ostb" \
  --password 'backup-passphrase' --yes >/dev/null
"$WORK/new/bin/ostium" user list --json > "$WORK/restored-users.json"
grep -q '"alice"' "$WORK/restored-users.json" || fail "restored backup lost user alice"
[[ "$(sha256sum "$DATA/master.key" | awk '{print $1}')" == "$OLD_KEY" ]] \
  || fail "restored backup replaced master.key"

# A token created by 0.1.1 must still resolve after restore.  This checks the
# subscription lookup without exposing the token in logs.
python3 - "$WORK/new/bin/python" "$OLD_TOKEN" <<'PY'
import subprocess
import sys

python, token = sys.argv[1:3]
code = f"""
import asyncio
from ostium.config import Settings
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.crypto import SecretStore
from ostium.services.users import get_user_by_subscription_token

async def main():
    settings = Settings.load()
    engine = create_engine(settings.paths.db_path)
    await create_schema(engine)
    store = SecretStore.from_data_dir(settings.data_dir)
    async with create_session_factory(engine)() as session:
        user = await get_user_by_subscription_token(session, store, {token!r})
        if user is None or user.name != "alice":
            raise SystemExit("subscription token did not survive the upgrade")
    await engine.dispose()
    print("subscription token survived")

asyncio.run(main())
"""
subprocess.run([python, "-c", code], check=True)
PY

say "upgrade and restore e2e passed: $FROM_VERSION -> $VERSION"
