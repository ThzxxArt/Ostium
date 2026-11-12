#!/usr/bin/env bash
# Ostium release installer for Linux server and client.
#
# Usage:
#   sudo ./install.sh --role server --wheel ./ostium_ctl-0.1.0-py3-none-any.whl \
#        --core ./ostium-core-1.14.4-ostium.1-linux-amd64.tar.gz --domain vpn.example.com
#   sudo ./install.sh --role client --wheel ... --core ...
set -euo pipefail

ROLE="server"
WHEEL=""
CORE=""
DOMAIN=""
PUBLIC_UI="false"
START="true"
ADMIN_PASSWORD=""
PREFIX="/opt/ostium"
DATA="/var/lib/ostium"
CONFIG="/etc/ostium"
CLIENT_DATA="/var/lib/ostium-core"
CLIENT_CONFIG="/etc/ostium/client.toml"

usage() {
  cat <<'EOF'
Ostium installer options:
  --role server|client       Role for this machine (default: server)
  --wheel PATH               Path to ostium_ctl-*.whl
  --core PATH                Path to ostium-core-*.tar.gz
  --domain DOMAIN            Server domain (optional for Reality)
  --public-ui                Expose the server admin UI publicly (TLS + TOTP required later)
  --password PASSWORD        Initial administrator password (generated if omitted)
  --no-start                 Install and enable services but do not start them
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --role) ROLE="$2"; shift 2 ;;
    --wheel) WHEEL="$2"; shift 2 ;;
    --core) CORE="$2"; shift 2 ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    --public-ui) PUBLIC_UI="true"; shift ;;
    --password) ADMIN_PASSWORD="$2"; shift 2 ;;
    --no-start) START="false"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root (sudo ./install.sh ...)" >&2
  exit 1
fi
if [[ "$ROLE" != "server" && "$ROLE" != "client" ]]; then
  echo "--role must be server or client" >&2
  exit 2
fi
if [[ -z "$WHEEL" || ! -f "$WHEEL" ]]; then
  echo "provide --wheel /path/to/ostium_ctl-*.whl" >&2
  exit 2
fi
if [[ -z "$CORE" || ! -f "$CORE" ]]; then
  echo "provide --core /path/to/ostium-core-*.tar.gz" >&2
  exit 2
fi
if [[ -z "$ADMIN_PASSWORD" ]]; then
  ADMIN_PASSWORD="$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 24)"
fi

export DEBIAN_FRONTEND=noninteractive
if command -v apt-get >/dev/null; then
  apt-get update
  apt-get install -y --no-install-recommends python3.13 python3.13-venv ca-certificates curl tar || true
fi

PYTHON_BIN="$(command -v python3.13 || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  if ! command -v uv >/dev/null; then
    install -d -m 0755 "$PREFIX/uv"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$PREFIX/uv" sh
  fi
  UV_BIN="$(command -v uv || echo "$PREFIX/uv/uv")"
  "$UV_BIN" python install 3.13
  PYTHON_BIN="$("$UV_BIN" python find 3.13)"
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "Python 3.13 is required; install python3.13 or uv first" >&2
  exit 1
fi

if [[ "$ROLE" == "server" ]]; then
  id -u ostium >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin ostium
  install -d -m 0750 -o ostium -g ostium "$DATA" "$DATA/runtime" "$DATA/logs" "$DATA/backups" "$DATA/certs" "$DATA/core" "$CONFIG"
else
  getent group ostium >/dev/null || groupadd --system ostium
  id -u ostium-core >/dev/null 2>&1 || useradd --system --gid ostium --home-dir "$CLIENT_DATA" --shell /usr/sbin/nologin ostium-core
  install -d -m 0750 -o ostium-core -g ostium "$CLIENT_DATA" "$CLIENT_DATA/runtime" "$CLIENT_DATA/logs" "$CLIENT_DATA/core"
  install -d -m 0755 "$CONFIG"
  if [[ -n "${SUDO_USER:-}" ]]; then
    usermod -aG ostium "$SUDO_USER"
  fi
fi

install -d -m 0755 "$PREFIX"
"$PYTHON_BIN" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --no-cache-dir --upgrade pip wheel
"$PREFIX/venv/bin/pip" install --no-cache-dir "$WHEEL"
ln -sfn "$PREFIX/venv/bin/ostium" /usr/local/bin/ostium

CORE_TMP="$(mktemp -d)"
tar -xzf "$CORE" -C "$CORE_TMP"
if [[ "$ROLE" == "server" ]]; then
  install -m 0755 "$CORE_TMP/sing-box" "$DATA/core/sing-box"
  chown ostium:ostium "$DATA/core/sing-box"
  cat >"$CONFIG/config.toml" <<EOF
role = "server"
host = "0.0.0.0"
port = 8443
public_ui = $PUBLIC_UI
data_dir = "$DATA"
config_dir = "$CONFIG"
log_level = "info"
engine_version = "1.14.4-ostium.1"
core_url = "http://127.0.0.1:8788"
EOF
  chown ostium:ostium "$CONFIG/config.toml"
  chmod 0600 "$CONFIG/config.toml"
  OSTIUM_ROLE=server OSTIUM_DATA_DIR="$DATA" OSTIUM_CONFIG_FILE="$CONFIG/config.toml" \
    "$PREFIX/venv/bin/ostium" init --role server --no-input --password "$ADMIN_PASSWORD" ${DOMAIN:+--domain "$DOMAIN"}
  install -m 0644 "$(dirname "$0")/../deploy/systemd/ostium.service" /etc/systemd/system/ostium.service
  install -m 0644 "$(dirname "$0")/../deploy/systemd/ostium-core.service" /etc/systemd/system/ostium-core.service
  systemctl daemon-reload
  systemctl enable ostium-core ostium
  if [[ "$START" == "true" ]]; then
    systemctl restart ostium-core
    systemctl restart ostium
  fi
  cat <<EOF

Ostium server installed.

  Admin password: $ADMIN_PASSWORD
  Admin URL:      http://127.0.0.1:8443  (SSH tunnel recommended)
  Proxy ports:    443/tcp (Reality), 443/udp (Hysteria2), 8388 (SS2022, disabled)
  Data:           $DATA

Open the firewall for 80, 443/tcp, 443/udp and (only if intended) 8443/tcp.
The password is shown once. Sign in and enable TOTP before exposing the UI.
EOF
else
  install -m 0755 "$CORE_TMP/sing-box" "$CLIENT_DATA/core/sing-box"
  chown ostium-core:ostium "$CLIENT_DATA/core/sing-box"
  cat >"$CLIENT_CONFIG" <<EOF
role = "client"
host = "127.0.0.1"
port = 8787
data_dir = "$CLIENT_DATA"
config_dir = "$CONFIG"
log_level = "info"
engine_version = "1.14.4-ostium.1"
core_url = "http://127.0.0.1:8788"
mode = "system_proxy"
EOF
  chmod 0640 "$CLIENT_CONFIG"
  chown root:ostium "$CLIENT_CONFIG"
  install -m 0644 "$(dirname "$0")/../deploy/systemd/ostium-core-client.service" /etc/systemd/system/ostium-core.service
  systemctl daemon-reload
  systemctl enable ostium-core
  if [[ "$START" == "true" ]]; then
    systemctl restart ostium-core
    sleep 1
    chmod 0640 "$CLIENT_DATA/core.token" 2>/dev/null || true
    chgrp ostium "$CLIENT_DATA/core.token" 2>/dev/null || true
  fi
  if [[ -n "${SUDO_USER:-}" ]]; then
    USER_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
    sudo -u "$SUDO_USER" mkdir -p "$USER_HOME/.config/systemd/user"
    install -m 0644 "$(dirname "$0")/../deploy/systemd/user/ostium.service" "$USER_HOME/.config/systemd/user/ostium.service"
    sudo -u "$SUDO_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$SUDO_USER")" systemctl --user daemon-reload || true
    sudo -u "$SUDO_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$SUDO_USER")" systemctl --user enable ostium.service || true
    echo "Client UI: log out and back in (to pick up the ostium group), then run: systemctl --user start ostium"
  fi
  cat <<EOF

Ostium client core installed.

  Core data:  $CLIENT_DATA
  UI:         http://127.0.0.1:8787
  Next:       start the user UI service and import a subscription.
EOF
fi

rm -rf "$CORE_TMP"
