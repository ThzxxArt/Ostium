#!/usr/bin/env bash
# Run the real Linux installer into a temporary prefix without systemd or root.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
WORK="${OSTIUM_INSTALL_E2E_DIR:-$(mktemp -d -t ostium-install-XXXXXX)}"
CORE="${OSTIUM_INSTALL_E2E_CORE:-/tmp/opencode/rel4/ostium-core-1.14.4-ostium.1-linux-amd64.tar.gz}"
KEEP="${OSTIUM_INSTALL_E2E_KEEP:-false}"

say() { echo "[install-e2e] $*"; }
fail() { echo "[install-e2e] error: $*" >&2; exit 1; }

cleanup() {
  if [[ "$KEEP" != "true" ]]; then
    rm -rf "$WORK"
  else
    say "keeping work directory: $WORK"
  fi
}
trap cleanup EXIT

[[ -f "$CORE" ]] || fail "core archive not found: $CORE (set OSTIUM_INSTALL_E2E_CORE)"
mkdir -p "$WORK/dist"
say "building $VERSION wheel"
SETUPTOOLS_SCM_PRETEND_VERSION="v$VERSION" uv build --wheel --out-dir "$WORK/dist" "$ROOT" >/dev/null
WHEEL="$(find "$WORK/dist" -maxdepth 1 -name 'ostium_ctl-*.whl' | head -1)"
[[ -n "$WHEEL" ]] || fail "wheel was not built"

PREFIX="$WORK/opt"
DATA="$WORK/data"
CONFIG="$WORK/config"
CLIENT_DATA="$WORK/client-data"
CLIENT_UI_DATA="$WORK/client-ui-data"
BIN="$WORK/bin/ostium"
SYSTEMD="$WORK/systemd"

export OSTIUM_PREFIX="$PREFIX"
export OSTIUM_DATA_DIR="$CLIENT_DATA"
export OSTIUM_CONFIG_DIR="$CONFIG"
export OSTIUM_CLIENT_DATA_DIR="$CLIENT_DATA"
export OSTIUM_CLIENT_UI_DATA="$CLIENT_UI_DATA"
export OSTIUM_BIN_LINK="$BIN"
export OSTIUM_SYSTEMD_DIR="$SYSTEMD"

as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  elif unshare -r true >/dev/null 2>&1; then
    unshare -r "$@"
  else
    fail "install.sh requires root; run this script as root or with user namespaces"
  fi
}

say "running install.sh (client, no-service, run-as-root)"
as_root bash "$ROOT/scripts/install.sh" \
  --role client \
  --wheel "$WHEEL" \
  --core "$CORE" \
  --run-as-root --no-service --no-start >/dev/null

[[ -x "$PREFIX/venv/bin/ostium" ]] || fail "venv CLI was not installed"
[[ -x "$BIN" ]] || fail "bin link was not installed"
REPORTED="$("$PREFIX/venv/bin/ostium" version 2>/dev/null | sed -n '1p')"
[[ "$REPORTED" == *"$VERSION"* ]] || fail "installed CLI reports '$REPORTED', expected $VERSION"
[[ -f "$CLIENT_DATA/core/sing-box" ]] || fail "core binary was not installed"
[[ -f "$CONFIG/client.toml" ]] || fail "client configuration was not created"

say "re-running the installer (idempotent reinstall)"
as_root bash "$ROOT/scripts/install.sh" \
  --role client \
  --wheel "$WHEEL" \
  --core "$CORE" \
  --run-as-root --no-service --no-start >/dev/null

say "installing and reinstalling the server role over an existing database"
SERVER_DATA="$WORK/server-data"
SERVER_CONFIG="$WORK/server-config"
SAVED_DATA="${OSTIUM_DATA_DIR:-}"
SAVED_CONFIG="${OSTIUM_CONFIG_DIR:-}"
export OSTIUM_DATA_DIR="$SERVER_DATA" OSTIUM_CONFIG_DIR="$SERVER_CONFIG"
as_root bash "$ROOT/scripts/install.sh" \
  --role server --wheel "$WHEEL" --core "$CORE" \
  --run-as-root --no-service --no-start --password 'verysecret123' >/dev/null
# A repair/reinstall has an existing database and therefore no generated
# password.  The installer must not pass an empty --password (the CLI rejects
# it), and init must keep the existing administrator.
as_root bash "$ROOT/scripts/install.sh" \
  --role server --wheel "$WHEEL" --core "$CORE" \
  --run-as-root --no-service --no-start >/dev/null
OSTIUM_ROLE=server OSTIUM_DATA_DIR="$SERVER_DATA" OSTIUM_CONFIG_DIR="$SERVER_CONFIG" \
  "$PREFIX/venv/bin/ostium" user list --json >/dev/null
python3 - "$SERVER_DATA/ostium.db" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as connection:
    admins = connection.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
if admins != 1:
    raise SystemExit(f"expected one administrator after reinstall, found {admins}")
print("server reinstall kept exactly one administrator")
PY
export OSTIUM_DATA_DIR="$SAVED_DATA" OSTIUM_CONFIG_DIR="$SAVED_CONFIG"

say "uninstalling with purge"
as_root bash "$ROOT/scripts/install.sh" \
  --role client \
  --run-as-root --uninstall --purge >/dev/null

[[ ! -e "$PREFIX" ]] || fail "prefix still exists after purge"
[[ ! -e "$DATA" ]] || fail "client data still exists after purge"
[[ ! -e "$CLIENT_UI_DATA" ]] || fail "UI data still exists after purge"
say "install/reinstall/uninstall e2e passed for $VERSION"
