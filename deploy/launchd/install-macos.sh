#!/usr/bin/env bash
# Install Ostium on macOS (run from the release directory as root).
# Environment:
#   OSTIUM_PYTHON       Python 3.13 binary (default: python3)
#   OSTIUM_WHEEL        Path to the Ostium wheel
#   OSTIUM_CORE_TARBALL Path to the macOS sing-box core archive
#   OSTIUM_RUN_AS_ROOT  true = run both LaunchDaemons as root (no user isolation)
#   OSTIUM_NO_SERVICE   true = install files only, do not register launchd
#   OSTIUM_NO_START     true = register launchd but do not start
set -euo pipefail

ROLE="${1:-client}"
PREFIX="${OSTIUM_PREFIX:-/opt/ostium}"
DATA="/Library/Application Support/Ostium"
UI_DATA="/Library/Application Support/Ostium UI"
PYTHON_BIN="${OSTIUM_PYTHON:-python3}"
RUN_AS_ROOT="${OSTIUM_RUN_AS_ROOT:-false}"
NO_SERVICE="${OSTIUM_NO_SERVICE:-false}"
NO_START="${OSTIUM_NO_START:-false}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root: sudo ./install-macos.sh client" >&2
  exit 1
fi
if [[ "$ROLE" != "client" ]]; then
  echo "macOS is supported as a client; run the Linux installer for the server." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WHEEL="${OSTIUM_WHEEL:-$(find "$SCRIPT_DIR" -maxdepth 1 -name 'ostium_ctl-*.whl' | head -1)}"
CORE_TARBALL="${OSTIUM_CORE_TARBALL:-$(find "$SCRIPT_DIR" -maxdepth 1 -name 'ostium-core-*-darwin-*.tar.gz' | head -1)}"
if [[ -z "$WHEEL" || ! -f "$WHEEL" ]]; then
  echo "provide OSTIUM_WHEEL or place ostium_ctl-*.whl beside this script" >&2
  exit 2
fi
if [[ -z "$CORE_TARBALL" || ! -f "$CORE_TARBALL" ]]; then
  echo "provide OSTIUM_CORE_TARBALL or place ostium-core-*-darwin-*.tar.gz beside this script" >&2
  exit 2
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python 3.13 is required: $PYTHON_BIN" >&2
  exit 2
fi

CORE_DIR="$(mktemp -d)"
trap 'rm -rf "$CORE_DIR"' EXIT
tar -xzf "$CORE_TARBALL" -C "$CORE_DIR" --no-same-owner

mkdir -p "$PREFIX" "$DATA" "$DATA/logs" "$DATA/core" "$UI_DATA" "$UI_DATA/logs"
"$PYTHON_BIN" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --no-cache-dir --upgrade pip wheel
"$PREFIX/venv/bin/pip" install --no-cache-dir "$WHEEL"
ln -sfn "$PREFIX/venv/bin/ostium" /usr/local/bin/ostium

install -m 0755 "$CORE_DIR/sing-box" "$PREFIX/sing-box"
install -m 0755 "$CORE_DIR/sing-box" "$DATA/core/sing-box"

if [[ ! -f "$DATA/ostium.db" ]]; then
  OSTIUM_ROLE=client OSTIUM_DATA_DIR="$DATA" \
    "$PREFIX/venv/bin/ostium" init --role client --no-input \
    --password "$(openssl rand -base64 18)" || true
fi

if [[ "$NO_SERVICE" == "true" ]]; then
  cat <<EOF

Ostium macOS client installed without launchd.

  Core:  sudo OSTIUM_ROLE=client OSTIUM_DATA_DIR="$DATA" $PREFIX/venv/bin/ostium core-run
  UI:    OSTIUM_ROLE=client OSTIUM_CORE_URL=http://127.0.0.1:8788 $PREFIX/venv/bin/ostium serve

  Data:  $DATA
  UI data: $UI_DATA
EOF
  exit 0
fi

# Remove previous registrations before switching modes.
launchctl unload -w /Library/LaunchDaemons/com.ostium.core.plist 2>/dev/null || true
launchctl unload -w /Library/LaunchDaemons/com.ostium.ui.plist 2>/dev/null || true
launchctl unload -w /Library/LaunchAgents/com.ostium.ui.plist 2>/dev/null || true

install -m 0644 "$SCRIPT_DIR/com.ostium.core.plist" /Library/LaunchDaemons/
if [[ "$RUN_AS_ROOT" == "true" ]]; then
  install -m 0644 "$SCRIPT_DIR/com.ostium.ui.root.plist" /Library/LaunchDaemons/com.ostium.ui.plist
  rm -f /Library/LaunchAgents/com.ostium.ui.plist
else
  install -m 0644 "$SCRIPT_DIR/com.ostium.ui.plist" /Library/LaunchAgents/
  rm -f /Library/LaunchDaemons/com.ostium.ui.plist
fi

if [[ "$NO_START" != "true" ]]; then
  launchctl load -w /Library/LaunchDaemons/com.ostium.core.plist
  if [[ "$RUN_AS_ROOT" == "true" ]]; then
    launchctl load -w /Library/LaunchDaemons/com.ostium.ui.plist
  else
    launchctl load -w /Library/LaunchAgents/com.ostium.ui.plist
  fi
fi

cat <<EOF

Ostium macOS client installed.

  Data:       $DATA
  UI data:    $UI_DATA
  UI:         http://127.0.0.1:8787
  Run as:     $([[ "$RUN_AS_ROOT" == "true" ]] && echo root || echo "root core + logged-in user UI")
EOF
