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
if [[ ! -x "$CORE_DIR/sing-box" ]] || ! "$CORE_DIR/sing-box" version >/dev/null 2>&1; then
  echo "核心包内缺少可运行的 sing-box" >&2
  exit 2
fi

case "$PREFIX" in
  *[[:space:]\&\#\|\\\"\']*)
    echo "OSTIUM_PREFIX 不能包含空白、引号、&、#、| 或反斜杠：$PREFIX" >&2
    exit 2
    ;;
esac
mkdir -p "$PREFIX" "$DATA" "$DATA/logs" "$DATA/core" "$UI_DATA" "$UI_DATA/logs"

render_plist() {
  local source="$1" target="$2"
  sed "s#/opt/ostium#$PREFIX#g" "$source" >"$target"
  chmod 0644 "$target"
}
VENV="$PREFIX/venv"
OLD_VENV=""
if [[ -d "$VENV" ]]; then
  OLD_VENV="$PREFIX/venv.old"
  rm -rf "$OLD_VENV"
  mv "$VENV" "$OLD_VENV"
fi
if ! "$PYTHON_BIN" -m venv "$VENV" \
  || ! "$VENV/bin/pip" install --no-cache-dir --upgrade pip wheel \
  || ! "$VENV/bin/pip" install --no-cache-dir "$WHEEL"; then
  rm -rf "$VENV"
  if [[ -n "$OLD_VENV" ]]; then
    mv "$OLD_VENV" "$VENV"
  fi
  echo "Ostium 安装失败，旧虚拟环境已恢复" >&2
  exit 1
fi
if [[ -n "$OLD_VENV" ]]; then
  rm -rf "$OLD_VENV"
fi
ln -sfn "$PREFIX/venv/bin/ostium" /usr/local/bin/ostium

install -m 0755 "$CORE_DIR/sing-box" "$PREFIX/sing-box"
install -m 0755 "$CORE_DIR/sing-box" "$DATA/core/sing-box"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
for doc in LICENSE NOTICE; do
  if [[ -f "$ROOT_DIR/$doc" ]]; then
    install -m 0644 "$ROOT_DIR/$doc" "$PREFIX/$doc"
  fi
done
for doc in LICENSE SBOM.txt; do
  if [[ -f "$CORE_DIR/$doc" ]]; then
    install -m 0644 "$CORE_DIR/$doc" "$DATA/core/$doc"
  fi
done
true

# Clients do not have an installer-created administrator: the first visit to
# the UI runs the setup wizard, exactly like the Linux client.  Keep the core
# configuration separate from the UI database so the privileged core never
# needs to own the admin database.
if [[ ! -f "$DATA/config.toml" ]]; then
  cat >"$DATA/config.toml" <<EOF
role = "client"
host = "127.0.0.1"
port = 8787
data_dir = "$DATA"
config_dir = "$DATA"
log_level = "info"
engine_version = "1.14.4-ostium.1"
engine_path = "$DATA/core/sing-box"
core_url = "http://127.0.0.1:8788"
mode = "system_proxy"
EOF
  chmod 0600 "$DATA/config.toml"
fi

# The UI persists its own settings (Allow LAN, port, mode) in its data dir.
# Keep that file writable by the logged-in user without granting write access
# to the privileged core configuration.
if [[ ! -f "$UI_DATA/config.toml" ]]; then
  cat >"$UI_DATA/config.toml" <<EOF
role = "client"
host = "127.0.0.1"
port = 8787
data_dir = "$UI_DATA"
config_dir = "$UI_DATA"
log_level = "info"
engine_version = "1.14.4-ostium.1"
engine_path = "$DATA/core/sing-box"
core_url = "http://127.0.0.1:8788"
core_token_file = "$DATA/runtime/core.token"
mode = "system_proxy"
EOF
fi

# The unprivileged UI user needs to read the core token.  A dedicated local
# group is the macOS equivalent of the Linux ostium group.
if ! dseditgroup -o read ostium >/dev/null 2>&1; then
  if ! dseditgroup -o create ostium >/dev/null 2>&1; then
    echo "无法创建 ostium 组；UI 将无法读取核心 token" >&2
    exit 1
  fi
fi
UI_OWNER="${SUDO_USER:-root}"
if [[ "$UI_OWNER" != "root" ]]; then
  if ! dseditgroup -o edit -a "$UI_OWNER" -t user ostium >/dev/null 2>&1; then
    echo "无法把 $UI_OWNER 加入 ostium 组；UI 将无法读取核心 token" >&2
    exit 1
  fi
fi
chown -R "$UI_OWNER" "$UI_DATA"
chmod 0750 "$UI_DATA"
[[ -f "$UI_DATA/config.toml" ]] && chmod 0600 "$UI_DATA/config.toml"

if [[ "$NO_SERVICE" == "true" ]]; then
  cat <<EOF

Ostium macOS client installed without launchd.

  Core:  sudo OSTIUM_ROLE=client OSTIUM_DATA_DIR="$DATA" OSTIUM_SHARED_DATA=1 \\
           OSTIUM_CONFIG_FILE="$DATA/config.toml" $PREFIX/venv/bin/ostium core-run
  UI:    OSTIUM_ROLE=client OSTIUM_DATA_DIR="$UI_DATA" OSTIUM_CONFIG_DIR="$UI_DATA" \\
           OSTIUM_CONFIG_FILE="$UI_DATA/config.toml" \\
           OSTIUM_CORE_TOKEN_FILE="$DATA/runtime/core.token" OSTIUM_CORE_URL=http://127.0.0.1:8788 \\
           $PREFIX/venv/bin/ostium serve

  Data:  $DATA
  UI data: $UI_DATA
EOF
  if [[ "$UI_OWNER" != "root" ]]; then
    echo
    echo "请注销并重新登录，让 $UI_OWNER 获得 ostium 组权限后再启动 UI。"
  fi
  exit 0
fi

# Remove previous registrations before switching modes.
unload_agent() {
  if [[ -n "${SUDO_USER:-}" ]]; then
    launchctl asuser "$(id -u "$SUDO_USER")" launchctl unload -w "$1" 2>/dev/null || true
  else
    launchctl unload -w "$1" 2>/dev/null || true
  fi
}
launchctl unload -w /Library/LaunchDaemons/com.ostium.core.plist 2>/dev/null || true
launchctl unload -w /Library/LaunchDaemons/com.ostium.ui.plist 2>/dev/null || true
unload_agent /Library/LaunchAgents/com.ostium.ui.plist

render_plist "$SCRIPT_DIR/com.ostium.core.plist" /Library/LaunchDaemons/com.ostium.core.plist
if [[ "$RUN_AS_ROOT" == "true" ]]; then
  render_plist "$SCRIPT_DIR/com.ostium.ui.root.plist" /Library/LaunchDaemons/com.ostium.ui.plist
  rm -f /Library/LaunchAgents/com.ostium.ui.plist
else
  render_plist "$SCRIPT_DIR/com.ostium.ui.plist" /Library/LaunchAgents/com.ostium.ui.plist
  rm -f /Library/LaunchDaemons/com.ostium.ui.plist
fi

if [[ "$NO_START" != "true" ]]; then
  launchctl load -w /Library/LaunchDaemons/com.ostium.core.plist
  if [[ "$RUN_AS_ROOT" == "true" ]]; then
    launchctl load -w /Library/LaunchDaemons/com.ostium.ui.plist
  elif [[ -n "${SUDO_USER:-}" ]]; then
    launchctl asuser "$(id -u "$SUDO_USER")" launchctl load -w /Library/LaunchAgents/com.ostium.ui.plist
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

Open the UI to complete the client setup wizard.
EOF
if [[ "$RUN_AS_ROOT" != "true" && "$UI_OWNER" != "root" ]]; then
  echo "首次安装后请注销并重新登录，让 $UI_OWNER 获得 ostium 组权限，否则 UI 无法读取 core token。"
fi
