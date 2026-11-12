#!/usr/bin/env bash
# Install Ostium on macOS (run from the release directory as root).
set -euo pipefail

ROLE="${1:-client}"
PREFIX="/opt/ostium"
DATA="/Library/Application Support/Ostium"
CORE_DATA="/var/lib/ostium-core"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root: sudo ./install-macos.sh client" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WHEEL="$(find "$SCRIPT_DIR" -maxdepth 1 -name 'ostium_ctl-*.whl' | head -1)"
CORE_TARBALL="$(find "$SCRIPT_DIR" -maxdepth 1 -name 'ostium-core-*-darwin-*.tar.gz' | head -1)"
CORE_DIR="$(mktemp -d)"
tar -xzf "$CORE_TARBALL" -C "$CORE_DIR"

mkdir -p "$PREFIX" "$DATA" "$DATA/logs" "$CORE_DATA"
python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --no-cache-dir --upgrade pip
"$PREFIX/venv/bin/pip" install --no-cache-dir "$WHEEL"
ln -sfn "$PREFIX/venv/bin/ostium" /usr/local/bin/ostium

if [[ "$ROLE" == "server" ]]; then
  echo "macOS is supported as a client; run the Linux installer for the server." >&2
  exit 1
fi

install -m 0755 "$CORE_DIR/sing-box" "$PREFIX/sing-box"
mkdir -p "$DATA/core"
cp "$PREFIX/sing-box" "$DATA/core/sing-box"
chmod 0755 "$DATA/core/sing-box"

OSTIUM_ROLE=client OSTIUM_DATA_DIR="$DATA" "$PREFIX/venv/bin/ostium" init --role client --no-input --password "$(openssl rand -base64 18)" || true

install -m 0644 "$SCRIPT_DIR/com.ostium.core.plist" /Library/LaunchDaemons/
install -m 0644 "$SCRIPT_DIR/com.ostium.ui.plist" "/Library/LaunchAgents/"
launchctl load -w /Library/LaunchDaemons/com.ostium.core.plist
launchctl load -w /Library/LaunchAgents/com.ostium.ui.plist
echo "Ostium installed. Open http://127.0.0.1:8787"
