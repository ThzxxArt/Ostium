#!/usr/bin/env bash
# Ostium release installer for Linux server and client.
#
# Default mode creates an unprivileged service user and installs systemd units.
# --run-as-root runs both services as root without creating any service user.
# --no-service installs files only, for OpenRC/runit/s6/supervisord or manual use.
#
# Usage:
#   sudo ./install.sh --role server --wheel ./ostium_ctl-0.1.1-py3-none-any.whl \
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
UI_HOST="${OSTIUM_UI_HOST:-127.0.0.1}"
UI_PORT="${OSTIUM_UI_PORT:-8443}"
ALLOW_INSECURE_BIND="${OSTIUM_ALLOW_INSECURE_BIND:-false}"
START="true"
ADMIN_PASSWORD=""
PREFIX="${OSTIUM_PREFIX:-/opt/ostium}"
DATA="${OSTIUM_DATA_DIR:-/var/lib/ostium}"
CONFIG="${OSTIUM_CONFIG_DIR:-/etc/ostium}"
CLIENT_DATA="${OSTIUM_CLIENT_DATA_DIR:-/var/lib/ostium-core}"
CLIENT_UI_DATA="${OSTIUM_CLIENT_UI_DATA:-/var/lib/ostium}"
UI_DATA="$CLIENT_UI_DATA"
UI_CONFIG="$CLIENT_UI_DATA/config.toml"
CLIENT_CONFIG="${OSTIUM_CLIENT_CONFIG:-$CONFIG/client.toml}"
BIN_LINK="${OSTIUM_BIN_LINK:-/usr/local/bin/ostium}"
SYSTEMD_DIR="${OSTIUM_SYSTEMD_DIR:-/etc/systemd/system}"
PYTHON_BIN="${OSTIUM_PYTHON:-}"
RUN_AS_ROOT="false"
NO_SERVICE="false"
UPGRADE="false"
UNINSTALL="false"
PURGE="false"

usage() {
  cat <<'EOF'
Ostium 安装器参数：
  --role server|client       角色（默认 server）
  --wheel PATH               ostium_ctl-*.whl 路径
  --core PATH                ostium-core-*.tar.gz 路径
  --domain DOMAIN            服务端域名（Reality 可省略）
  --public-ui                已禁用；请在登录后签发证书、启用 TOTP，再从 Settings 开启
  --behind-proxy             Nginx/Caddy 反向代理模式：UI 只监听 127.0.0.1，启用 Secure Cookie
  --ui-host HOST             管理 UI 监听地址（默认 127.0.0.1；非 loopback 需 --allow-insecure-bind）
  --allow-insecure-bind      显式允许非 loopback 明文管理 UI（必须配合防火墙/反代）
  --ui-port PORT             管理 UI 端口（默认 8443）
  --secure-cookies           强制 Secure Cookie（HTTPS 反代时使用）
  --password PASSWORD        初始管理员密码（省略则随机生成）
  --python PATH              使用指定 Python 3.13，不安装系统 Python
  --run-as-root              不创建 ostium 用户，ostium/ostium-core 均以 root 运行
  --no-service               只安装文件，不注册 systemd（供 OpenRC/runit/s6/supervisord 使用）
  --upgrade                  升级模式：保留数据和配置，只替换程序与核心
  --uninstall                停止并移除服务与程序链接（默认保留数据/配置）
  --purge                    与 --uninstall 配合删除数据、配置、证书与密钥
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
    --allow-insecure-bind) ALLOW_INSECURE_BIND="true"; shift ;;
    --ui-port) UI_PORT="$2"; shift 2 ;;
    --secure-cookies) SECURE_COOKIES="true"; shift ;;
    --password) ADMIN_PASSWORD="$2"; shift 2 ;;
    --python) PYTHON_BIN="$2"; shift 2 ;;
    --run-as-root) RUN_AS_ROOT="true"; shift ;;
    --no-service) NO_SERVICE="true"; shift ;;
    --upgrade) UPGRADE="true"; shift ;;
    --uninstall) UNINSTALL="true"; shift ;;
    --purge) PURGE="true"; shift ;;
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
if [[ -n "$DOMAIN" && ! "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
  echo "--domain 不是有效域名：$DOMAIN" >&2
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
if [[ "$BEHIND_PROXY" == "true" ]]; then
  UI_HOST="127.0.0.1"
  ALLOW_INSECURE_BIND="false"
fi
case "$UI_HOST" in
  127.0.0.1|localhost|::1) ;;
  *)
    if [[ "$PUBLIC_UI" != "true" && "$ALLOW_INSECURE_BIND" != "true" ]]; then
      echo "拒绝在 $UI_HOST 上明文暴露管理 UI：请使用 127.0.0.1（SSH 隧道），或显式传入 --allow-insecure-bind 并配置防火墙/Nginx" >&2
      exit 2
    fi
    ;;
esac
if [[ "$BEHIND_PROXY" == "true" && "$PUBLIC_UI" == "true" ]]; then
  echo "--behind-proxy 与 --public-ui 互斥：前者由 Nginx 终止 TLS，后者由 Ostium 自己监听 TLS" >&2
  exit 2
fi

validate_install_path() {
  local path="$1" label="$2" normalized
  if [[ -z "$path" || "$path" != /* ]]; then
    echo "$label 必须是绝对路径：$path" >&2
    exit 2
  fi
  # The systemd renderer below is intentionally dependency-free.  Reject
  # characters that would change unit syntax or sed replacements instead of
  # silently writing a broken service.
  case "$path" in
    *[[:space:]\&\#\|\\\"\']*)
      echo "$label 不能包含空白、引号、&、#、| 或反斜杠：$path" >&2
      exit 2
      ;;
  esac
  if command -v realpath >/dev/null 2>&1; then
    normalized="$(realpath -m "$path" 2>/dev/null || echo "$path")"
  else
    normalized="$(printf '%s' "$path" | sed 's#//*#/#g; s#/$##')"
  fi
  case "$normalized" in
    /|/bin|/boot|/dev|/etc|/home|/lib|/lib64|/opt|/proc|/root|/run|/sbin|/srv|/sys|/tmp|/usr|/var|/var/lib|/var/log|/Library|/System|/Users|/Applications)
      echo "拒绝使用系统根目录作为 $label：$normalized" >&2
      exit 2
      ;;
  esac
  case "/$normalized/" in
    */../*)
      echo "$label 不能包含 ..：$path" >&2
      exit 2
      ;;
  esac
}

validate_install_path "$PREFIX" "安装目录"
validate_install_path "$DATA" "数据目录"
validate_install_path "$CONFIG" "配置目录"
validate_install_path "$CLIENT_DATA" "客户端核心数据目录"
validate_install_path "$CLIENT_UI_DATA" "客户端 UI 数据目录"
validate_install_path "$BIN_LINK" "可执行链接"
validate_install_path "$SYSTEMD_DIR" "systemd 目录"

if [[ "$UNINSTALL" == "true" ]]; then
  echo "停止 Ostium 服务……"
  if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
    systemctl disable --now ostium ostium-core 2>/dev/null || true
    rm -f "$SYSTEMD_DIR/ostium.service" "$SYSTEMD_DIR/ostium-core.service"
    rm -rf "$SYSTEMD_DIR/ostium.service.d" "$SYSTEMD_DIR/ostium-core.service.d"
    systemctl daemon-reload 2>/dev/null || true
    if [[ -n "${SUDO_USER:-}" ]]; then
      user_home="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
      sudo -u "$SUDO_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$SUDO_USER")" \
        systemctl --user disable --now ostium 2>/dev/null || true
      rm -f "$user_home/.config/systemd/user/ostium.service"
      sudo -u "$SUDO_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$SUDO_USER")" \
        systemctl --user daemon-reload 2>/dev/null || true
    fi
  fi
  # Restore the desktop proxy before deleting the CLI that knows how.
  if [[ -x "$BIN_LINK" ]]; then
    if [[ -n "${SUDO_USER:-}" ]]; then
      sudo -u "$SUDO_USER" "$BIN_LINK" proxy off >/dev/null 2>&1 || true
    else
      "$BIN_LINK" proxy off >/dev/null 2>&1 || true
    fi
  fi
  rm -f "$BIN_LINK"
  if [[ "$PURGE" == "true" ]]; then
    echo "删除数据、配置与程序目录（不可恢复）……" >&2
    rm -rf "$DATA" "$CONFIG" "$PREFIX" "$CLIENT_DATA" "$CLIENT_UI_DATA"
    echo "Ostium 已完全卸载（--purge）。"
  else
    echo "Ostium 程序与服务已移除；数据保留在："
    echo "  $DATA"
    echo "  $CONFIG"
    echo "  $CLIENT_DATA"
    echo "使用 --purge 可同时删除数据（不可恢复）。"
  fi
  exit 0
fi

TRUSTED_HOSTS_TOML='["localhost", "127.0.0.1", "::1"'
if [[ -n "$DOMAIN" ]]; then
  TRUSTED_HOSTS_TOML+=", \"$DOMAIN\""
fi
TRUSTED_HOSTS_TOML+=']'

# Public UI requires both a certificate and TOTP.  Neither can exist before
# the first local login, so enabling it during the initial install would make
# `ostium serve` exit and systemd restart it forever.  It must be a deliberate
# post-install step from Settings.
if [[ "$PUBLIC_UI" == "true" && "$UPGRADE" != "true" ]]; then
  echo "--public-ui 不能在首次安装时启用；请先本地安装，登录并启用 TOTP、签发/上传证书，再在 Settings 中启用 Public UI" >&2
  exit 2
fi

systemd_available() {
  command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]
}

stop_services() {
  if systemd_available; then
    # Keep the proxy core running during a control-plane upgrade so the
    # tunnel is not interrupted.  The old venv stays open by inode until the
    # new unit is restarted.
    systemctl stop ostium 2>/dev/null || true
    if [[ -n "${SUDO_USER:-}" ]]; then
      sudo -u "$SUDO_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$SUDO_USER")" \
        systemctl --user stop ostium 2>/dev/null || true
    fi
  fi
}

wait_for_url() {
  local url="$1"
  for _ in $(seq 1 20); do
    if curl -fsSk --max-time 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

rollback_control_plane() {
  local reason="$1"
  echo "升级健康检查失败（$reason），回滚到旧控制面……" >&2
  if systemd_available; then
    systemctl stop ostium 2>/dev/null || true
  fi
  if [[ -d "$PREFIX/venv.old" ]]; then
    rm -rf "$PREFIX/venv.failed"
    mv "$PREFIX/venv" "$PREFIX/venv.failed" 2>/dev/null || true
    mv "$PREFIX/venv.old" "$PREFIX/venv"
    if systemd_available; then
      systemctl start ostium 2>/dev/null || true
    fi
  fi
  echo "旧控制面已恢复；失败的新环境保留在 $PREFIX/venv.failed（如存在）。" >&2
  exit 1
}

rollback_core() {
  local destination="$1"
  echo "核心启动检查失败，回滚旧核心……" >&2
  if [[ -f "$destination.old" ]]; then
    mv -f "$destination.old" "$destination"
    if systemd_available; then
      systemctl restart ostium-core 2>/dev/null || true
    fi
  fi
  echo "旧核心已恢复。" >&2
  exit 1
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

# The shipped units use the default layout so they are readable and
# reviewable.  Installations may override prefix/data/config paths, so render
# the final unit rather than copying a unit that points at /opt/ostium.
render_unit() {
  local source="$1" target="$2" data_dir="$3" config_dir="$4" temporary
  if [[ ! -f "$source" ]]; then
    echo "缺少 systemd 单元文件：$source" >&2
    exit 1
  fi
  install -d -m 0755 "$(dirname "$target")"
  temporary="$(mktemp "$target.XXXXXX")"
  sed \
    -e "s#/opt/ostium#$PREFIX#g" \
    -e "s#/var/lib/ostium-core#$CLIENT_DATA#g" \
    -e "s#/var/lib/ostium#$data_dir#g" \
    -e "s#/etc/ostium/client.toml#$CLIENT_CONFIG#g" \
    -e "s#/etc/ostium#$config_dir#g" \
    "$source" >"$temporary"
  chmod 0644 "$temporary"
  mv -f "$temporary" "$target"
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

  sudo OSTIUM_ROLE=client OSTIUM_CONFIG_FILE=$CLIENT_CONFIG OSTIUM_SHARED_DATA=1 $PREFIX/venv/bin/ostium core-run

  OSTIUM_ROLE=client OSTIUM_CONFIG_FILE=$UI_CONFIG OSTIUM_CONFIG_DIR=$UI_DATA \\
    OSTIUM_DATA_DIR=$UI_DATA OSTIUM_CORE_TOKEN_FILE=$CLIENT_DATA/runtime/core.token \\
    OSTIUM_CORE_URL=http://127.0.0.1:8788 $PREFIX/venv/bin/ostium serve

核心数据：$CLIENT_DATA
核心配置：$CLIENT_CONFIG
UI 数据/配置：$UI_DATA
EOF
  fi
}

if [[ "$UPGRADE" == "true" ]]; then
  stop_services
fi

export DEBIAN_FRONTEND=noninteractive
if [[ -z "$PYTHON_BIN" ]]; then
  if command -v apt-get >/dev/null; then
    if ! apt-get update; then
      echo "警告：apt-get update 失败，继续使用现有软件源缓存" >&2
    fi
    if ! apt-get install -y --no-install-recommends python3.13 python3.13-venv ca-certificates curl tar; then
      echo "警告：系统 Python 3.13 安装失败，将尝试 uv 托管 Python" >&2
    fi
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
    install -d -m 0755 "$DATA" "$DATA/runtime" "$DATA/logs" "$DATA/backups" "$DATA/certs" \
      "$DATA/core" "$DATA/state" "$DATA/rulesets" "$CONFIG"
  else
    id -u ostium >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin ostium
    install -d -m 0750 -o ostium -g ostium "$DATA" "$DATA/runtime" "$DATA/logs" \
      "$DATA/backups" "$DATA/certs" "$DATA/core" "$DATA/state" "$DATA/rulesets"
    install -d -m 0750 -o ostium -g ostium "$CONFIG"
  fi
else
  if [[ "$RUN_AS_ROOT" == "true" ]]; then
    install -d -m 0755 "$CLIENT_DATA" "$CLIENT_DATA/runtime" "$CLIENT_DATA/logs" \
      "$CLIENT_DATA/core" "$CLIENT_DATA/state" "$CLIENT_DATA/rulesets"
    install -d -m 0755 "$CLIENT_UI_DATA" "$CLIENT_UI_DATA/logs" "$CLIENT_UI_DATA/state"
    install -d -m 0755 "$CONFIG"
  else
    getent group ostium >/dev/null || groupadd --system ostium
    id -u ostium-core >/dev/null 2>&1 || useradd --system --gid ostium --home-dir "$CLIENT_DATA" --shell /usr/sbin/nologin ostium-core
    install -d -m 0750 -o ostium-core -g ostium "$CLIENT_DATA" "$CLIENT_DATA/runtime" \
      "$CLIENT_DATA/logs" "$CLIENT_DATA/core" "$CLIENT_DATA/state" "$CLIENT_DATA/rulesets"
    install -d -m 0755 "$CONFIG"
    if [[ -z "${SUDO_USER:-}" ]]; then
      echo "无法确定桌面用户；请通过 sudo 运行，或显式使用 --run-as-root" >&2
      exit 1
    fi
    usermod -aG ostium "$SUDO_USER"
    USER_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
    UI_DATA="$USER_HOME/.local/share/ostium"
    UI_CONFIG="$UI_DATA/config.toml"
    install -d -m 0700 -o "$SUDO_USER" -g ostium "$UI_DATA"
  fi
fi

CORE_TMP="$(mktemp -d)"
trap 'rm -rf "$CORE_TMP"' EXIT
tar -xzf "$CORE" -C "$CORE_TMP" --no-same-owner
if [[ ! -x "$CORE_TMP/sing-box" ]]; then
  echo "核心包内缺少可执行的 sing-box" >&2
  exit 1
fi
if ! "$CORE_TMP/sing-box" version >/dev/null 2>&1; then
  echo "核心二进制无法运行，拒绝安装" >&2
  exit 1
fi

install -d -m 0755 "$PREFIX"
NEW_VENV=""
cleanup_new_venv() {
  if [[ -n "$NEW_VENV" && -d "$NEW_VENV" ]]; then
    rm -rf "$NEW_VENV"
  fi
}
trap 'rm -rf "$CORE_TMP"; cleanup_new_venv' EXIT
if [[ "$UPGRADE" == "true" ]]; then
  NEW_VENV="$PREFIX/venv.new.$$"
  if ! "$PYTHON_BIN" -m venv "$NEW_VENV"; then
    echo "无法创建升级用的虚拟环境" >&2
    exit 1
  fi
  if ! "$NEW_VENV/bin/pip" install --no-cache-dir --upgrade pip wheel \
    || ! "$NEW_VENV/bin/pip" install --no-cache-dir "$WHEEL"; then
    echo "升级失败，旧虚拟环境保持不变" >&2
    exit 1
  fi
  if [[ -d "$PREFIX/venv" ]]; then
    rm -rf "$PREFIX/venv.old"
    mv "$PREFIX/venv" "$PREFIX/venv.old"
  fi
  if ! mv "$NEW_VENV" "$PREFIX/venv"; then
    [[ -d "$PREFIX/venv.old" ]] && mv "$PREFIX/venv.old" "$PREFIX/venv"
    echo "无法切换虚拟环境，已回滚" >&2
    exit 1
  fi
  OLD_VENV="$NEW_VENV"
  NEW_VENV=""
  # pip writes the temporary venv path into console-script shebangs.  After
  # the atomic rename those paths no longer exist, so rewrite the scripts to
  # the final location before declaring the upgrade successful.
  for script in "$PREFIX/venv/bin/"*; do
    [[ -f "$script" && ! -L "$script" ]] || continue
    if [[ "$(head -n 1 "$script")" == "#!$OLD_VENV/"* ]]; then
      sed -i "1s|^#!$OLD_VENV/|#!$PREFIX/venv/|" "$script"
    fi
  done
else
  "$PYTHON_BIN" -m venv "$PREFIX/venv"
  "$PREFIX/venv/bin/pip" install --no-cache-dir --upgrade pip wheel
  "$PREFIX/venv/bin/pip" install --no-cache-dir "$WHEEL"
fi
install -d -m 0755 "$(dirname "$BIN_LINK")"
ln -sfn "$PREFIX/venv/bin/ostium" "$BIN_LINK"

install_core() {
  local destination="$1" owner="$2" temporary="$1.new.$$"
  if [[ -f "$destination" ]]; then
    cp -p "$destination" "$destination.old"
  fi
  if ! install -m 0755 "$CORE_TMP/sing-box" "$temporary"; then
    rm -f "$temporary"
    echo "无法写入核心二进制：$destination" >&2
    exit 1
  fi
  if [[ -n "$owner" ]]; then
    chown "$owner" "$temporary"
  fi
  mv -f "$temporary" "$destination"
}

install_license() {
  local target="$1"
  local source_root
  source_root="$(cd "$(dirname "$0")/.." && pwd)"
  install -d -m 0755 "$target/core"
  for doc in LICENSE NOTICE; do
    if [[ -f "$source_root/$doc" ]]; then
      install -m 0644 "$source_root/$doc" "$target/$doc"
    fi
  done
  for doc in LICENSE SBOM.txt; do
    if [[ -f "$CORE_TMP/$doc" ]]; then
      install -m 0644 "$CORE_TMP/$doc" "$target/core/$doc"
    fi
  done
  return 0
}

if [[ "$ROLE" == "server" ]]; then
  install_core "$DATA/core/sing-box" "$([[ "$RUN_AS_ROOT" == "true" ]] && echo "" || echo "ostium:ostium")"
  install_license "$PREFIX"
  if [[ "$UPGRADE" != "true" ]]; then
    cat >"$CONFIG/config.toml" <<EOF
role = "server"
host = "$UI_HOST"
port = $UI_PORT
public_ui = $PUBLIC_UI
allow_insecure_bind = $ALLOW_INSECURE_BIND
secure_cookies = $SECURE_COOKIES
trusted_hosts = $TRUSTED_HOSTS_TOML
data_dir = "$DATA"
config_dir = "$CONFIG"
log_level = "info"
engine_version = "1.14.4-ostium.1"
engine_path = "$DATA/core/sing-box"
core_url = "http://127.0.0.1:8788"
EOF
    chmod 0600 "$CONFIG/config.toml"
    if [[ "$RUN_AS_ROOT" != "true" ]]; then
      chown ostium:ostium "$CONFIG/config.toml"
    fi
    INIT_ARGS=(init --role server --no-input --password "$ADMIN_PASSWORD" --host "$UI_HOST" --port "$UI_PORT")
    [[ -n "$DOMAIN" ]] && INIT_ARGS+=(--domain "$DOMAIN")
    [[ "$PUBLIC_UI" == "true" ]] && INIT_ARGS+=(--public-ui)
    [[ "$ALLOW_INSECURE_BIND" == "true" ]] && INIT_ARGS+=(--allow-insecure-bind)
    OSTIUM_ROLE=server OSTIUM_DATA_DIR="$DATA" OSTIUM_CONFIG_FILE="$CONFIG/config.toml" \
      "$PREFIX/venv/bin/ostium" "${INIT_ARGS[@]}"
  elif [[ ! -f "$CONFIG/config.toml" ]]; then
    echo "升级模式需要已有配置：$CONFIG/config.toml" >&2
    exit 1
  fi
  if [[ "$UPGRADE" == "true" && -f "$CONFIG/config.toml" ]]; then
    if [[ "$ALLOW_INSECURE_BIND" != "true" && "$PUBLIC_UI" != "true" ]]; then
      if grep -Eq '^[[:space:]]*host[[:space:]]*=[[:space:]]*"0\.0\.0\.0"' "$CONFIG/config.toml"; then
        sed -i 's|^[[:space:]]*host[[:space:]]*=[[:space:]]*"0\.0\.0\.0"|host = "127.0.0.1"|' "$CONFIG/config.toml"
        echo "安全迁移：旧配置 host=0.0.0.0 已收敛为 127.0.0.1；如需保留请使用 --allow-insecure-bind 并配置防火墙。" >&2
      fi
    fi
    if grep -Eq '^[[:space:]]*allow_insecure_bind[[:space:]]*=' "$CONFIG/config.toml"; then
      sed -i "s|^[[:space:]]*allow_insecure_bind[[:space:]]*=.*|allow_insecure_bind = $ALLOW_INSECURE_BIND|" "$CONFIG/config.toml"
    else
      printf 'allow_insecure_bind = %s\n' "$ALLOW_INSECURE_BIND" >>"$CONFIG/config.toml"
    fi
  fi
  # `init` runs as root during install, so SQLite/WAL and master.key are
  # created with root ownership.  The service runs as ostium and must be able
  # to read the key and write the database.
  if [[ "$RUN_AS_ROOT" != "true" ]]; then
    chown -R ostium:ostium "$DATA" "$CONFIG"
  fi

  if [[ "$NO_SERVICE" != "true" ]] && systemd_available; then
    render_unit "$(dirname "$0")/../deploy/systemd/ostium.service" \
      "$SYSTEMD_DIR/ostium.service" "$DATA" "$CONFIG"
    render_unit "$(dirname "$0")/../deploy/systemd/ostium-core.service" \
      "$SYSTEMD_DIR/ostium-core.service" "$DATA" "$CONFIG"
    if [[ "$RUN_AS_ROOT" == "true" ]]; then
      write_root_dropin ostium.service
      write_root_dropin ostium-core.service
    fi
    systemctl daemon-reload
    systemctl enable ostium-core ostium
    if [[ "$START" == "true" ]]; then
      systemctl restart ostium-core
      systemctl restart ostium
      if [[ "$UPGRADE" == "true" ]]; then
        sleep 1
        if ! systemctl is-active --quiet ostium-core \
          || ! curl -fsS --max-time 3 http://127.0.0.1:8788/v1/health 2>/dev/null \
            | grep -q '"running"[[:space:]]*:[[:space:]]*true'; then
          rollback_core "$DATA/core/sing-box"
        fi
        HEALTH_SCHEME="http"
        [[ "$PUBLIC_UI" == "true" ]] && HEALTH_SCHEME="https"
        if ! wait_for_url "$HEALTH_SCHEME://127.0.0.1:$UI_PORT/healthz" \
          || ! wait_for_url "$HEALTH_SCHEME://127.0.0.1:$UI_PORT/readyz"; then
          rollback_control_plane "control plane health/readiness check"
        fi
        rm -rf "$PREFIX/venv.old"
        rm -f "$DATA/core/sing-box.old"
      fi
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
  install_core "$CLIENT_DATA/core/sing-box" "$([[ "$RUN_AS_ROOT" == "true" ]] && echo "" || echo "ostium-core:ostium")"
  install_license "$PREFIX"
  if [[ "$UPGRADE" != "true" ]]; then
    cat >"$CLIENT_CONFIG" <<EOF
role = "client"
host = "127.0.0.1"
port = 8787
data_dir = "$CLIENT_DATA"
config_dir = "$CONFIG"
log_level = "info"
engine_version = "1.14.4-ostium.1"
engine_path = "$CLIENT_DATA/core/sing-box"
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
  # The UI user only needs read access to the privileged core config; group
  # write would let the UI rewrite engine_path before the core starts.
  chmod 0640 "$CLIENT_CONFIG" 2>/dev/null || true
  if [[ "$RUN_AS_ROOT" != "true" ]]; then
    chown root:ostium "$CLIENT_CONFIG" 2>/dev/null || true
  fi

  if [[ ! -f "$UI_CONFIG" ]]; then
    cat >"$UI_CONFIG" <<EOF
role = "client"
host = "127.0.0.1"
port = 8787
data_dir = "$UI_DATA"
config_dir = "$UI_DATA"
log_level = "info"
engine_version = "1.14.4-ostium.1"
engine_path = "$CLIENT_DATA/core/sing-box"
core_url = "http://127.0.0.1:8788"
core_token_file = "$CLIENT_DATA/runtime/core.token"
mode = "system_proxy"
EOF
    UI_OWNER="${SUDO_USER:-root}"
    [[ "$RUN_AS_ROOT" == "true" ]] && UI_OWNER="root"
    chown "$UI_OWNER" "$UI_CONFIG"
    chmod 0600 "$UI_CONFIG"
  fi

  if [[ "$NO_SERVICE" != "true" ]] && systemd_available; then
    render_unit "$(dirname "$0")/../deploy/systemd/ostium-core-client.service" \
      "$SYSTEMD_DIR/ostium-core.service" "$CLIENT_DATA" "$CLIENT_DATA"
    if [[ "$RUN_AS_ROOT" == "true" ]]; then
      write_root_dropin ostium-core.service
      render_unit "$(dirname "$0")/../deploy/systemd/ostium-client-ui.service" \
        "$SYSTEMD_DIR/ostium.service" "$UI_DATA" "$UI_DATA"
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
        chmod 0640 "$CLIENT_DATA/runtime/core.token" 2>/dev/null || true
        chgrp ostium "$CLIENT_DATA/runtime/core.token" 2>/dev/null || true
        if [[ "$UPGRADE" == "true" ]]; then
          if ! systemctl is-active --quiet ostium-core \
            || ! curl -fsS --max-time 3 http://127.0.0.1:8788/v1/health 2>/dev/null \
              | grep -q '"running"[[:space:]]*:[[:space:]]*true'; then
            rollback_core "$CLIENT_DATA/core/sing-box"
          fi
          rm -rf "$PREFIX/venv.old"
          rm -f "$CLIENT_DATA/core/sing-box.old"
        fi
      fi
      if [[ -n "${SUDO_USER:-}" ]]; then
        USER_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
        sudo -u "$SUDO_USER" mkdir -p "$USER_HOME/.config/systemd/user"
        render_unit "$(dirname "$0")/../deploy/systemd/user/ostium.service" \
          "$USER_HOME/.config/systemd/user/ostium.service" "$UI_DATA" "$UI_DATA"
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
