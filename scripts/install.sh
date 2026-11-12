#!/usr/bin/env bash
# Ostium release installer for Linux server and client.
#
# Default mode creates an unprivileged service user and installs systemd units.
# --run-as-root runs both services as root without creating any service user.
# --no-service installs files only, for OpenRC/runit/s6/supervisord or manual use.
#
# Usage:
#   sudo ./install.sh --role server --wheel ./ostium_ctl-0.1.0-py3-none-any.whl \
#        --core ./ostium-core-1.14.4-ostium.1-linux-amd64.tar.gz --domain vpn.example.com
#   sudo ./install.sh --role client --wheel ... --core ...
#   sudo ./install.sh --role server ... --run-as-root
#   sudo ./install.sh --role client ... --no-service
set -euo pipefail

ROLE="server"
WHEEL=""
CORE=""
DOMAIN=""
PUBLIC_UI="false"
BEHIND_PROXY="false"
SECURE_COOKIES="false"
UI_HOST="${OSTIUM_UI_HOST:-0.0.0.0}"
UI_PORT="${OSTIUM_UI_PORT:-8443}"
START="true"
ADMIN_PASSWORD=""
PREFIX="${OSTIUM_PREFIX:-/opt/ostium}"
DATA="${OSTIUM_DATA_DIR:-/var/lib/ostium}"
CONFIG="${OSTIUM_CONFIG_DIR:-/etc/ostium}"
CLIENT_DATA="${OSTIUM_CLIENT_DATA_DIR:-/var/lib/ostium-core}"
CLIENT_UI_DATA="${OSTIUM_CLIENT_UI_DATA:-/var/lib/ostium}"
CLIENT_CONFIG="${OSTIUM_CLIENT_CONFIG:-/etc/ostium/client.toml}"
BIN_LINK="${OSTIUM_BIN_LINK:-/usr/local/bin/ostium}"
SYSTEMD_DIR="${OSTIUM_SYSTEMD_DIR:-/etc/systemd/system}"
PYTHON_BIN="${OSTIUM_PYTHON:-}"
RUN_AS_ROOT="false"
NO_SERVICE="false"
UPGRADE="false"

usage() {
  cat <<'EOF'
Ostium 安装器参数：
  --role server|client       角色（默认 server）
  --wheel PATH               ostium_ctl-*.whl 路径
  --core PATH                ostium-core-*.tar.gz 路径
  --domain DOMAIN            服务端域名（Reality 可省略）
  --public-ui                允许公网访问管理 UI（需先启用 TLS + TOTP）
  --behind-proxy             Nginx/Caddy 反向代理模式：UI 只监听 127.0.0.1，启用 Secure Cookie
  --ui-host HOST             管理 UI 监听地址（默认 0.0.0.0；--behind-proxy 强制 127.0.0.1）
  --ui-port PORT             管理 UI 端口（默认 8443）
  --secure-cookies           强制 Secure Cookie（HTTPS 反代时使用）
  --password PASSWORD        初始管理员密码（省略则随机生成）
  --python PATH              使用指定 Python 3.13，不安装系统 Python
  --run-as-root              不创建 ostium 用户，ostium/ostium-core 均以 root 运行
  --no-service               只安装文件，不注册 systemd（供 OpenRC/runit/s6/supervisord 使用）
  --upgrade                  升级模式：保留数据和配置，只替换程序与核心
  --no-start                 注册服务但不启动
  -h, --help                 显示帮助

安全提示：
  默认模式是推荐配置：控制面以普通用户运行，只有核心服务拥有低端口/TUN 权限。
  --run-as-root 会取消这层隔离，任何 Web/API 漏洞都可能直接获得 root 权限。
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --role) ROLE="$2"; shift 2 ;;
    --wheel) WHEEL="$2"; shift 2 ;;
    --core) CORE="$2"; shift 2 ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    --public-ui) PUBLIC_UI="true"; shift ;;
    --behind-proxy) BEHIND_PROXY="true"; shift ;;
    --ui-host) UI_HOST="$2"; shift 2 ;;
    --ui-port) UI_PORT="$2"; shift 2 ;;
    --secure-cookies) SECURE_COOKIES="true"; shift ;;
    --password) ADMIN_PASSWORD="$2"; shift 2 ;;
    --python) PYTHON_BIN="$2"; shift 2 ;;
    --run-as-root) RUN_AS_ROOT="true"; shift ;;
    --no-service) NO_SERVICE="true"; shift ;;
    --upgrade) UPGRADE="true"; shift ;;
    --no-start) START="false"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请使用 root 运行：sudo ./install.sh ..." >&2
  exit 1
fi
if [[ "$ROLE" != "server" && "$ROLE" != "client" ]]; then
  echo "--role 必须是 server 或 client" >&2
  exit 2
fi
if [[ -z "$WHEEL" || ! -f "$WHEEL" ]]; then
  echo "请提供 --wheel /path/to/ostium_ctl-*.whl" >&2
  exit 2
fi
if [[ -z "$CORE" || ! -f "$CORE" ]]; then
  echo "请提供 --core /path/to/ostium-core-*.tar.gz" >&2
  exit 2
fi
if [[ -n "$PYTHON_BIN" && ! -x "$PYTHON_BIN" ]]; then
  echo "--python 不可执行：$PYTHON_BIN" >&2
  exit 2
fi
if [[ -z "$ADMIN_PASSWORD" && "$UPGRADE" != "true" ]]; then
  ADMIN_PASSWORD="$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 24)"
fi
if [[ "$BEHIND_PROXY" == "true" ]]; then
  UI_HOST="127.0.0.1"
  SECURE_COOKIES="true"
  if [[ -z "$DOMAIN" ]]; then
    echo "警告：--behind-proxy 建议同时提供 --domain，否则 trusted_hosts 不包含反代域名" >&2
  fi
fi
if [[ "$PUBLIC_UI" == "true" ]]; then
  SECURE_COOKIES="true"
fi
TRUSTED_HOSTS_TOML='["localhost", "127.0.0.1", "::1"'
if [[ -n "$DOMAIN" ]]; then
  TRUSTED_HOSTS_TOML+=", \"$DOMAIN\""
fi
TRUSTED_HOSTS_TOML+=']'

systemd_available() {
  command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]
}

stop_services() {
  if systemd_available; then
    systemctl stop ostium ostium-core 2>/dev/null || true
    if [[ -n "${SUDO_USER:-}" ]]; then
      sudo -u "$SUDO_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$SUDO_USER")" \
        systemctl --user stop ostium 2>/dev/null || true
    fi
  fi
}

write_root_dropin() {
  local unit="$1"
  install -d -m 0755 "$SYSTEMD_DIR/${unit}.d"
  cat >"$SYSTEMD_DIR/${unit}.d/root.conf" <<EOF
[Service]
User=root
Group=root
EOF
}

install_unit() {
  local source="$1" target="$2"
  if [[ ! -f "$source" ]]; then
    echo "缺少 systemd 单元文件：$source" >&2
    exit 1
  fi
  install -m 0644 "$source" "$SYSTEMD_DIR/$target"
}

print_manual_start() {
  if [[ "$ROLE" == "server" ]]; then
    cat <<EOF

未注册 systemd。可交给 OpenRC/runit/s6/supervisord，或直接运行：

  sudo OSTIUM_ROLE=server OSTIUM_CONFIG_FILE=$CONFIG/config.toml $PREFIX/venv/bin/ostium core-run
  sudo OSTIUM_ROLE=server OSTIUM_CONFIG_FILE=$CONFIG/config.toml $PREFIX/venv/bin/ostium serve

数据目录：$DATA
配置目录：$CONFIG
EOF
  else
    cat <<EOF

未注册 systemd。可交给 OpenRC/runit/s6/supervisord，或直接运行：

  sudo OSTIUM_ROLE=client OSTIUM_CONFIG_FILE=$CLIENT_CONFIG $PREFIX/venv/bin/ostium core-run
  OSTIUM_ROLE=client OSTIUM_DATA_DIR=$CLIENT_UI_DATA OSTIUM_CONFIG_DIR=$CONFIG \
    OSTIUM_CORE_TOKEN_FILE=$CLIENT_DATA/core.token OSTIUM_CORE_URL=http://127.0.0.1:8788 \
    $PREFIX/venv/bin/ostium serve

核心数据：$CLIENT_DATA
客户端配置：$CLIENT_CONFIG
EOF
  fi
}

if [[ "$UPGRADE" == "true" ]]; then
  stop_services
fi

export DEBIAN_FRONTEND=noninteractive
if [[ -z "$PYTHON_BIN" ]]; then
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
    UV_CACHE_DIR="${UV_CACHE_DIR:-$PREFIX/uv-cache}" "$UV_BIN" python install 3.13
    PYTHON_BIN="$(UV_CACHE_DIR="${UV_CACHE_DIR:-$PREFIX/uv-cache}" "$UV_BIN" python find 3.13)"
  fi
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "需要 Python 3.13：请安装 python3.13，或让一键脚本提供托管 Python" >&2
  exit 1
fi

if [[ "$ROLE" == "server" ]]; then
  if [[ "$RUN_AS_ROOT" == "true" ]]; then
    install -d -m 0755 "$DATA" "$DATA/runtime" "$DATA/logs" "$DATA/backups" "$DATA/certs" "$DATA/core" "$CONFIG"
  else
    id -u ostium >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin ostium
    install -d -m 0750 -o ostium -g ostium "$DATA" "$DATA/runtime" "$DATA/logs" "$DATA/backups" "$DATA/certs" "$DATA/core"
    install -d -m 0750 -o ostium -g ostium "$CONFIG"
  fi
else
  if [[ "$RUN_AS_ROOT" == "true" ]]; then
    install -d -m 0755 "$CLIENT_DATA" "$CLIENT_DATA/runtime" "$CLIENT_DATA/logs" "$CLIENT_DATA/core"
    install -d -m 0755 "$CLIENT_UI_DATA" "$CLIENT_UI_DATA/logs"
    install -d -m 0755 "$CONFIG"
  else
    getent group ostium >/dev/null || groupadd --system ostium
    id -u ostium-core >/dev/null 2>&1 || useradd --system --gid ostium --home-dir "$CLIENT_DATA" --shell /usr/sbin/nologin ostium-core
    install -d -m 0750 -o ostium-core -g ostium "$CLIENT_DATA" "$CLIENT_DATA/runtime" "$CLIENT_DATA/logs" "$CLIENT_DATA/core"
    install -d -m 0755 "$CONFIG"
    if [[ -n "${SUDO_USER:-}" ]]; then
      usermod -aG ostium "$SUDO_USER"
    fi
  fi
fi

install -d -m 0755 "$PREFIX"
if [[ "$UPGRADE" == "true" ]]; then
  rm -rf "$PREFIX/venv"
fi
"$PYTHON_BIN" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --no-cache-dir --upgrade pip wheel
"$PREFIX/venv/bin/pip" install --no-cache-dir "$WHEEL"
install -d -m 0755 "$(dirname "$BIN_LINK")"
ln -sfn "$PREFIX/venv/bin/ostium" "$BIN_LINK"

CORE_TMP="$(mktemp -d)"
trap 'rm -rf "$CORE_TMP"' EXIT
tar -xzf "$CORE" -C "$CORE_TMP" --no-same-owner

if [[ "$ROLE" == "server" ]]; then
  install -m 0755 "$CORE_TMP/sing-box" "$DATA/core/sing-box"
  if [[ "$RUN_AS_ROOT" != "true" ]]; then
    chown ostium:ostium "$DATA/core/sing-box"
  fi
  if [[ "$UPGRADE" != "true" ]]; then
    cat >"$CONFIG/config.toml" <<EOF
role = "server"
host = "$UI_HOST"
port = $UI_PORT
public_ui = $PUBLIC_UI
secure_cookies = $SECURE_COOKIES
trusted_hosts = $TRUSTED_HOSTS_TOML
data_dir = "$DATA"
config_dir = "$CONFIG"
log_level = "info"
engine_version = "1.14.4-ostium.1"
core_url = "http://127.0.0.1:8788"
EOF
    chmod 0600 "$CONFIG/config.toml"
    if [[ "$RUN_AS_ROOT" != "true" ]]; then
      chown ostium:ostium "$CONFIG/config.toml"
    fi
    INIT_ARGS=(init --role server --no-input --password "$ADMIN_PASSWORD" --host "$UI_HOST" --port "$UI_PORT")
    [[ -n "$DOMAIN" ]] && INIT_ARGS+=(--domain "$DOMAIN")
    [[ "$PUBLIC_UI" == "true" ]] && INIT_ARGS+=(--public-ui)
    OSTIUM_ROLE=server OSTIUM_DATA_DIR="$DATA" OSTIUM_CONFIG_FILE="$CONFIG/config.toml" \
      "$PREFIX/venv/bin/ostium" "${INIT_ARGS[@]}"
  elif [[ ! -f "$CONFIG/config.toml" ]]; then
    echo "升级模式需要已有配置：$CONFIG/config.toml" >&2
    exit 1
  fi

  if [[ "$NO_SERVICE" != "true" ]] && systemd_available; then
    install_unit "$(dirname "$0")/../deploy/systemd/ostium.service" ostium.service
    install_unit "$(dirname "$0")/../deploy/systemd/ostium-core.service" ostium-core.service
    if [[ "$RUN_AS_ROOT" == "true" ]]; then
      write_root_dropin ostium.service
      write_root_dropin ostium-core.service
    fi
    systemctl daemon-reload
    systemctl enable ostium-core ostium
    if [[ "$START" == "true" ]]; then
      systemctl restart ostium-core
      systemctl restart ostium
    fi
  else
    print_manual_start
  fi

  if [[ "$BEHIND_PROXY" == "true" ]]; then
    ADMIN_URL="https://${DOMAIN:-your-domain} （Nginx/Caddy 反代到 127.0.0.1:$UI_PORT）"
  elif [[ "$PUBLIC_UI" == "true" ]]; then
    ADMIN_URL="https://${DOMAIN:-your-domain}"
  else
    ADMIN_URL="http://127.0.0.1:$UI_PORT  （建议使用 SSH 隧道）"
  fi
  cat <<EOF

Ostium 服务端已安装。

  管理密码：$([[ "$UPGRADE" == "true" ]] && echo "未更改（升级模式）" || echo "$ADMIN_PASSWORD")
  管理地址：$ADMIN_URL
  数据目录：$DATA
  配置目录：$CONFIG
  运行身份：$([[ "$RUN_AS_ROOT" == "true" ]] && echo root || echo ostium)

防火墙需放行 80/tcp、443/tcp、443/udp；不要默认暴露 8443。
$([[ "$UPGRADE" == "true" ]] && echo "升级完成，数据与管理员密码保持不变。" || echo "密码只显示一次，登录后请立即启用 TOTP。")
EOF
else
  install -m 0755 "$CORE_TMP/sing-box" "$CLIENT_DATA/core/sing-box"
  if [[ "$RUN_AS_ROOT" != "true" ]]; then
    chown ostium-core:ostium "$CLIENT_DATA/core/sing-box"
  fi
  if [[ "$UPGRADE" != "true" ]]; then
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
    if [[ "$RUN_AS_ROOT" != "true" ]]; then
      chown root:ostium "$CLIENT_CONFIG"
    fi
  elif [[ ! -f "$CLIENT_CONFIG" ]]; then
    echo "升级模式需要已有配置：$CLIENT_CONFIG" >&2
    exit 1
  fi

  if [[ "$NO_SERVICE" != "true" ]] && systemd_available; then
    install_unit "$(dirname "$0")/../deploy/systemd/ostium-core-client.service" ostium-core.service
    if [[ "$RUN_AS_ROOT" == "true" ]]; then
      write_root_dropin ostium-core.service
      install_unit "$(dirname "$0")/../deploy/systemd/ostium-client-ui.service" ostium.service
      systemctl daemon-reload
      systemctl enable ostium-core ostium
      if [[ "$START" == "true" ]]; then
        systemctl restart ostium-core
        systemctl restart ostium
      fi
    else
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
        echo "客户端 UI：注销并重新登录（让 $SUDO_USER 获得 ostium 组），然后运行 systemctl --user start ostium"
      fi
    fi
  else
    print_manual_start
  fi

  cat <<EOF

Ostium 客户端已安装。

  核心数据：$CLIENT_DATA
  客户端配置：$CLIENT_CONFIG
  Web UI：http://127.0.0.1:8787
  运行身份：$([[ "$RUN_AS_ROOT" == "true" ]] && echo root || echo "ostium-core + 当前用户 UI")

下一步：打开 Web UI，完成向导并导入订阅。
EOF
fi
