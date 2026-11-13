#!/usr/bin/env bash
# Ostium 一键在线安装器（Linux 服务端/客户端、macOS 客户端）。
#
# 设计目标：机器上没有 Python 也能安装。脚本会：
#   1. 安装 curl/tar 等最小依赖（Linux，仅在缺失时）
#   2. 下载静态 uv，并用 uv 安装托管的 Python 3.13
#   3. 从 GitHub Release 下载 wheel、sing-box 核心和 SHA256SUMS
#   4. 校验后调用仓库内的平台安装器，注册服务
#
# 用法：
#   curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/scripts/install-online.sh \
#     | sudo bash -s -- install --role server --domain vpn.example.com
#
#   curl -fsSL .../install-online.sh | sudo bash -s -- install --role client
#   sudo bash install-online.sh upgrade
#   sudo bash install-online.sh uninstall [--purge]
#   sudo bash install-online.sh status
#
# 离线/内网：
#   sudo bash install-online.sh install --local-dir /path/to/source-checkout
set -euo pipefail

VERSION="${OSTIUM_VERSION:-0.1.0}"
CORE_VERSION="${OSTIUM_CORE_VERSION:-1.14.4-ostium.1}"
UV_VERSION="${OSTIUM_UV_VERSION:-0.11.14}"
ROLE="server"
DOMAIN=""
PASSWORD=""
PREFIX="${OSTIUM_PREFIX:-/opt/ostium}"
DATA="${OSTIUM_DATA_DIR:-/var/lib/ostium}"
CONFIG="${OSTIUM_CONFIG_DIR:-/etc/ostium}"
CLIENT_DATA="${OSTIUM_CLIENT_DATA_DIR:-/var/lib/ostium-core}"
CLIENT_UI_DATA="${OSTIUM_CLIENT_UI_DATA:-/var/lib/ostium}"
BIN_LINK="${OSTIUM_BIN_LINK:-/usr/local/bin/ostium}"
SYSTEMD_DIR="${OSTIUM_SYSTEMD_DIR:-/etc/systemd/system}"
PUBLIC_UI="false"
START="true"
ACTION="install"
LOCAL_DIR=""
RUN_AS_ROOT="false"
NO_SERVICE="false"
BEHIND_PROXY="false"
UI_HOST=""
UI_PORT=""
PURGE="false"
VERIFY="true"
WORK_DIR=""

usage() {
  cat <<'EOF'
Ostium 一键安装器

用法：
  install-online.sh [install] [选项]     安装或重装
  install-online.sh upgrade [选项]       升级程序与核心，保留数据和配置
  install-online.sh uninstall [--purge]  卸载程序，默认保留数据
  install-online.sh status               查看服务状态

选项：
  --role server|client       角色（默认 server；macOS 仅支持 client）
  --domain DOMAIN            服务端域名
  --password PASSWORD        初始管理员密码（省略则随机生成）
  --version VERSION          Release 版本（默认 0.1.0，可写 latest）
  --prefix PATH              安装目录（默认 /opt/ostium）
  --local-dir DIR            离线安装：包含 scripts/install.sh 的源码 checkout
  --run-as-root              不创建 ostium 用户，所有服务以 root 运行（降低隔离，谨慎使用）
  --no-service               不注册 systemd/launchd，交给 OpenRC/runit/s6/supervisord
  --behind-proxy             Nginx/Caddy 反代模式：UI 只监听 127.0.0.1，启用 Secure Cookie
  --ui-host HOST             管理 UI 监听地址（默认 0.0.0.0）
  --ui-port PORT             管理 UI 端口（默认 8443）
  --public-ui                已禁用；请在登录后签发证书、启用 TOTP，再从 Settings 开启
  --no-start                 注册服务但不启动
  --no-verify                跳过 SHA256 校验（仅限本地开发，勿用于生产）
  --purge                    卸载时同时删除数据、配置和用户
  -h, --help                 显示帮助

示例：
  curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/scripts/install-online.sh \
    | sudo bash -s -- install --role server --domain vpn.example.com

  curl -fsSL .../install-online.sh | sudo bash -s -- install --role client

  sudo bash install-online.sh install --role server --run-as-root
  sudo bash install-online.sh install --role client --no-service

安全提示：
  默认安装会创建无特权 ostium 用户，控制面不接触 root/TUN 权限。
  --run-as-root 适合单用户测试机或你已经用其他方式隔离了 Web/API 风险的环境。
EOF
}

say() { printf '\033[1;36m[Ostium]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[Ostium]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[Ostium]\033[0m %s\n' "$*" >&2; exit 1; }

need_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    die "请使用 sudo 运行，例如：curl ... | sudo bash -s -- install --role server"
  fi
}

validate_install_path() {
  local path="$1" label="$2" normalized
  if [[ -z "$path" || "$path" != /* ]]; then
    die "$label 必须是绝对路径：$path"
  fi
  case "$path" in
    *[[:space:]\&\#\|\\\"\']*)
      die "$label 不能包含空白、引号、&、#、| 或反斜杠：$path"
      ;;
  esac
  if command -v realpath >/dev/null 2>&1; then
    normalized="$(realpath -m "$path" 2>/dev/null || printf '%s' "$path")"
  else
    normalized="$(printf '%s' "$path" | sed 's#//*#/#g; s#/$##')"
  fi
  case "$normalized" in
    /|/bin|/boot|/dev|/etc|/home|/lib|/lib64|/opt|/proc|/root|/run|/sbin|/srv|/sys|/tmp|/usr|/var|/var/lib|/var/log|/Library|/System|/Users|/Applications)
      die "拒绝使用系统根目录作为 $label：$normalized"
      ;;
  esac
  case "/$normalized/" in
    */../*) die "$label 不能包含 ..：$path" ;;
  esac
}

cleanup() {
  if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT

fetch_file() {
  local url="$1" output="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 --connect-timeout 15 -o "$output" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$output" "$url"
  else
    die "需要 curl 或 wget 下载安装文件"
  fi
}

fetch_text() {
  local url="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 --connect-timeout 15 "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$url"
  else
    die "需要 curl 或 wget"
  fi
}

sha256_file() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  else
    die "需要 sha256sum 或 shasum"
  fi
}

verify_asset() {
  local file="$1" sums="$2"
  [[ "$VERIFY" == "true" ]] || { warn "已跳过校验：$(basename "$file")"; return; }
  [[ -f "$sums" ]] || die "缺少 SHA256SUMS：$sums"
  local name expected actual
  name="$(basename "$file")"
  expected="$(awk -v name="$name" '{base=$2; sub(/^.*\//, "", base); if (base == name) {print $1; exit}}' "$sums")"
  [[ -n "$expected" ]] || die "SHA256SUMS 中找不到 $name"
  actual="$(sha256_file "$file")"
  if [[ "$actual" != "$expected" ]]; then
    die "校验失败：$name\n  期望：$expected\n  实际：$actual"
  fi
  say "校验通过：$name"
}

detect_platform() {
  case "$(uname -s)" in
    Linux) OS="linux" ;;
    Darwin) OS="darwin" ;;
    *) die "仅支持 Linux 和 macOS；Windows 请使用 scripts/install-online.ps1" ;;
  esac
  case "$(uname -m)" in
    x86_64|amd64) ARCH="amd64" ;;
    arm64|aarch64) ARCH="arm64" ;;
    *) die "暂不支持架构：$(uname -m)" ;;
  esac
  if [[ "$OS" == "darwin" && "$ROLE" == "server" \
    && "$ACTION" != "status" && "$ACTION" != "uninstall" ]]; then
    die "macOS 仅支持客户端；服务端请使用 Linux"
  fi
}

ensure_tools() {
  local missing=()
  command -v tar >/dev/null 2>&1 || missing+=(tar)
  if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    missing+=(curl)
  fi
  [[ ${#missing[@]} -eq 0 ]] && return
  say "安装最小依赖：${missing[*]}"
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y --no-install-recommends ca-certificates curl tar
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y ca-certificates curl tar
  elif command -v yum >/dev/null 2>&1; then
    yum install -y ca-certificates curl tar
  else
    die "缺少 ${missing[*]}，请先手动安装 curl、tar、ca-certificates"
  fi
}

resolve_version() {
  if [[ "$VERSION" == "latest" ]]; then
    VERSION="$(fetch_text https://api.github.com/repos/ThzxxArt/Ostium/releases/latest \
      | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"v\{0,1\}\([^"]*\)".*/\1/p' | head -1)"
    [[ -n "$VERSION" ]] || die "无法解析最新版本，请用 --version 指定"
    say "最新版本：$VERSION"
  fi
}

find_asset() {
  local dir="$1" pattern="$2"
  find "$dir" -maxdepth 4 -type f -name "$pattern" -print -quit 2>/dev/null || true
}

# Return the basename of an entry in SHA256SUMS matching a regex.  The sums
# file is the only version-aware index: wheel filenames are PEP 440-normalised
# (for example 0.2.0rc1), so constructing names from the tag is unsafe.
sums_asset() {
  local pattern="$1" preferred="$2" value
  value="$(awk -v preferred="$preferred" -v pattern="$pattern" '
    {
      name = $2
      sub(/^.*\//, "", name)
      if (name ~ pattern) {
        if (preferred != "" && index(name, preferred) == 1) { print name; exit }
        if (fallback == "") { fallback = name }
      }
    }
    END { if (fallback != "") print fallback }
  ' "$3")"
  printf '%s' "$value"
}

# Extract the installer, service units and platform scripts from the signed
# source distribution.  Release users should never need a Git checkout, and
# executing an unverified GitHub-generated archive as root is not acceptable.
extract_source() {
  local archive="$1" directory
  mkdir -p "$WORK_DIR/source"
  tar -xzf "$archive" -C "$WORK_DIR/source" --no-same-owner
  directory="$(find "$WORK_DIR/source" -maxdepth 2 -type d -name 'ostium_ctl-*' -print -quit)"
  [[ -n "$directory" && -f "$directory/scripts/install.sh" ]] \
    || die "源码包中缺少 scripts/install.sh：$archive"
  printf '%s' "$directory"
}

download_release() {
  WORK_DIR="$(mktemp -d /tmp/ostium-install.XXXXXX)"
  if [[ -n "$LOCAL_DIR" ]]; then
    [[ -d "$LOCAL_DIR" ]] || die "本地目录不存在：$LOCAL_DIR"
    SOURCE_DIR="$LOCAL_DIR"
    SUMS="$(find_asset "$LOCAL_DIR" 'SHA256SUMS')"
    WHEEL="$(find_asset "$LOCAL_DIR" "ostium_ctl-${VERSION}-*.whl")"
    [[ -n "$WHEEL" ]] || WHEEL="$(find_asset "$LOCAL_DIR" 'ostium_ctl-*.whl')"
    CORE="$(find_asset "$LOCAL_DIR" "ostium-core-*-${OS}-${ARCH}.tar.gz")"
    SDIST="$(find_asset "$LOCAL_DIR" "ostium_ctl-${VERSION}.tar.gz")"
    [[ -n "$SDIST" ]] || SDIST="$(find_asset "$LOCAL_DIR" 'ostium_ctl-*.tar.gz')"
    say "使用本地目录：$LOCAL_DIR"
    if [[ ! -f "$SOURCE_DIR/scripts/install.sh" ]]; then
      [[ -n "$SDIST" ]] \
        || die "本地目录需要包含 scripts/install.sh 或 ostium_ctl-*.tar.gz：$LOCAL_DIR"
      verify_asset "$SDIST" "$SUMS"
      SOURCE_DIR="$(extract_source "$SDIST")"
    fi
  else
    local base="https://github.com/ThzxxArt/Ostium/releases/download/v${VERSION}"
    SUMS="$WORK_DIR/SHA256SUMS"
    say "下载 Ostium v${VERSION}（${OS}/${ARCH}）"
    fetch_file "${base}/SHA256SUMS" "$SUMS"
    local wheel_name sdist_name
    wheel_name="$(sums_asset '^ostium_ctl-.*\.whl$' "ostium_ctl-${VERSION}-" "$SUMS")"
    sdist_name="$(sums_asset '^ostium_ctl-.*\.tar\.gz$' "ostium_ctl-${VERSION}" "$SUMS")"
    [[ -n "$wheel_name" ]] || die "SHA256SUMS 中找不到 wheel"
    [[ -n "$sdist_name" ]] || die "SHA256SUMS 中找不到 sdist"
    WHEEL="$WORK_DIR/$wheel_name"
    SDIST="$WORK_DIR/$sdist_name"
    CORE="$WORK_DIR/ostium-core-${CORE_VERSION}-${OS}-${ARCH}.tar.gz"
    fetch_file "${base}/${wheel_name}" "$WHEEL"
    fetch_file "${base}/${sdist_name}" "$SDIST"
    fetch_file "${base}/$(basename "$CORE")" "$CORE"
    verify_asset "$WHEEL" "$SUMS"
    verify_asset "$SDIST" "$SUMS"
    SOURCE_DIR="$(extract_source "$SDIST")"
  fi
  [[ -f "$WHEEL" ]] || die "找不到 wheel：$WHEEL"
  [[ -f "$CORE" ]] || die "找不到核心包：$CORE"
  verify_asset "$WHEEL" "$SUMS"
  verify_asset "$CORE" "$SUMS"
}

bootstrap_python() {
  local uv_target
  case "$OS/$ARCH" in
    linux/amd64) uv_target="x86_64-unknown-linux-gnu" ;;
    linux/arm64) uv_target="aarch64-unknown-linux-gnu" ;;
    darwin/amd64) uv_target="x86_64-apple-darwin" ;;
    darwin/arm64) uv_target="aarch64-apple-darwin" ;;
    *) die "不支持的平台：$OS/$ARCH" ;;
  esac

  UV_BIN="$PREFIX/uv/uv"
  if [[ ! -x "$UV_BIN" ]]; then
    say "安装静态 uv（无需系统 Python）"
    local archive="$WORK_DIR/uv.tar.gz"
    fetch_file "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${uv_target}.tar.gz" "$archive"
    local checksum="$WORK_DIR/uv.tar.gz.sha256"
    if fetch_file "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${uv_target}.tar.gz.sha256" "$checksum" 2>/dev/null; then
      local expected actual
      expected="$(awk '{print $1; exit}' "$checksum")"
      actual="$(sha256_file "$archive")"
      [[ "$expected" == "$actual" ]] || die "uv 校验失败"
    else
      warn "未能获取 uv 校验文件，继续安装"
    fi
    install -d -m 0755 "$PREFIX/uv"
    tar -xzf "$archive" -C "$PREFIX/uv" --strip-components=1 --no-same-owner
  fi
  [[ -x "$UV_BIN" ]] || die "uv 安装失败：$UV_BIN"

  export UV_CACHE_DIR="$PREFIX/uv-cache"
  export UV_PYTHON_INSTALL_DIR="$PREFIX/python"
  say "安装托管 Python 3.13（不依赖系统 Python）"
  "$UV_BIN" python install 3.13
  PYTHON_BIN="$(find "$PREFIX/python" -type f -path '*/bin/python3.13' -print -quit 2>/dev/null || true)"
  if [[ -z "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$("$UV_BIN" python find --managed-python --no-project 3.13)"
  fi
  [[ -x "$PYTHON_BIN" ]] || die "托管 Python 安装失败"
  say "Python：$PYTHON_BIN"
}

systemd_available() {
  command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]
}

detect_existing_mode() {
  if [[ "$RUN_AS_ROOT" != "true" ]]; then
    if [[ -f "$SYSTEMD_DIR/ostium.service.d/root.conf" ]] \
      || [[ -f "$SYSTEMD_DIR/ostium-core.service.d/root.conf" ]]; then
      RUN_AS_ROOT="true"
      say "检测到已有 root 模式，升级将保持该模式"
    fi
  fi
  if [[ "$NO_SERVICE" != "true" && "$OS" == "linux" ]] && ! systemd_available; then
    NO_SERVICE="true"
    warn "未检测到 systemd，自动使用 --no-service 模式"
  fi
}

run_platform_installer() {
  local extra=()
  [[ "$RUN_AS_ROOT" == "true" ]] && extra+=(--run-as-root)
  [[ "$NO_SERVICE" == "true" ]] && extra+=(--no-service)
  [[ "$ACTION" == "upgrade" ]] && extra+=(--upgrade)
  [[ "$START" == "false" ]] && extra+=(--no-start)
  [[ "$PUBLIC_UI" == "true" ]] && extra+=(--public-ui)
  if [[ "$OS" == "linux" ]]; then
    [[ "$BEHIND_PROXY" == "true" ]] && extra+=(--behind-proxy)
    [[ -n "$UI_HOST" ]] && extra+=(--ui-host "$UI_HOST")
    [[ -n "$UI_PORT" ]] && extra+=(--ui-port "$UI_PORT")
  elif [[ "$BEHIND_PROXY" == "true" ]]; then
    warn "macOS 一键安装暂不支持 --behind-proxy；请安装后编辑 launchd 配置"
  fi

  export OSTIUM_PREFIX="$PREFIX"
  if [[ "$OS" == "linux" ]]; then
    chmod +x "$SOURCE_DIR/scripts/install.sh"
    "$SOURCE_DIR/scripts/install.sh" \
      --role "$ROLE" \
      --wheel "$WHEEL" \
      --core "$CORE" \
      --python "$PYTHON_BIN" \
      --domain "$DOMAIN" \
      --password "$PASSWORD" \
      "${extra[@]+"${extra[@]}"}"
  else
    export OSTIUM_PYTHON="$PYTHON_BIN"
    export OSTIUM_WHEEL="$WHEEL"
    export OSTIUM_CORE_TARBALL="$CORE"
    export OSTIUM_RUN_AS_ROOT="$RUN_AS_ROOT"
    export OSTIUM_NO_SERVICE="$NO_SERVICE"
    [[ "$START" == "false" ]] && export OSTIUM_NO_START=1
    chmod +x "$SOURCE_DIR/deploy/launchd/install-macos.sh"
    "$SOURCE_DIR/deploy/launchd/install-macos.sh" client
  fi
}

uninstall_ostium() {
  say "停止并移除 Ostium 服务"
  if [[ "$OS" == "linux" ]]; then
    if systemd_available; then
      systemctl disable --now ostium ostium-core 2>/dev/null || true
    fi
    rm -rf "$SYSTEMD_DIR/ostium.service.d" "$SYSTEMD_DIR/ostium-core.service.d"
    rm -f "$SYSTEMD_DIR/ostium.service" "$SYSTEMD_DIR/ostium-core.service"
    if command -v systemctl >/dev/null 2>&1; then
      systemctl daemon-reload 2>/dev/null || true
    fi
    if [[ -n "${SUDO_USER:-}" ]]; then
      local home
      home="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
      rm -f "$home/.config/systemd/user/ostium.service"
      sudo -u "$SUDO_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$SUDO_USER")" \
        systemctl --user daemon-reload 2>/dev/null || true
    fi
  elif [[ "$OS" == "darwin" ]]; then
    launchctl unload -w /Library/LaunchDaemons/com.ostium.core.plist 2>/dev/null || true
    launchctl unload -w /Library/LaunchDaemons/com.ostium.ui.plist 2>/dev/null || true
    if [[ -n "${SUDO_USER:-}" ]]; then
      launchctl asuser "$(id -u "$SUDO_USER")" \
        launchctl unload -w /Library/LaunchAgents/com.ostium.ui.plist 2>/dev/null || true
    else
      launchctl unload -w /Library/LaunchAgents/com.ostium.ui.plist 2>/dev/null || true
    fi
    rm -f /Library/LaunchDaemons/com.ostium.core.plist \
      /Library/LaunchDaemons/com.ostium.ui.plist \
      /Library/LaunchAgents/com.ostium.ui.plist
  fi
  rm -f "$BIN_LINK"
  rm -rf "$PREFIX"
  if [[ "$PURGE" == "true" ]]; then
    rm -rf "$DATA" "$CLIENT_DATA" "$CLIENT_UI_DATA" "$CONFIG"
    rm -rf "/Library/Application Support/Ostium" "/Library/Application Support/Ostium UI"
    if id -u ostium >/dev/null 2>&1; then userdel ostium 2>/dev/null || true; fi
    if id -u ostium-core >/dev/null 2>&1; then userdel ostium-core 2>/dev/null || true; fi
    say "已删除程序和全部数据"
  else
    say "已移除程序；数据与配置保留（使用 --purge 可一并删除）"
  fi
}

show_status() {
  say "Ostium 状态"
  if [[ -x "$BIN_LINK" ]]; then
    "$BIN_LINK" version 2>/dev/null || true
  fi
  if [[ "$OS" == "linux" ]] && systemd_available; then
    systemctl status ostium-core ostium --no-pager 2>/dev/null || true
  elif [[ "$OS" == "darwin" ]]; then
    launchctl list | grep -E 'com\.ostium' || true
  fi
  if [[ ! -d "$PREFIX" ]]; then
    warn "未发现安装目录：$PREFIX"
  fi
}

if [[ $# -gt 0 && "$1" != -* ]]; then
  ACTION="$1"
  shift
fi
case "$ACTION" in
  install|upgrade|uninstall|status) ;;
  *) usage; die "未知动作：$ACTION" ;;
esac

while [[ $# -gt 0 ]]; do
  case "$1" in
    --role) ROLE="$2"; shift 2 ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    --password) PASSWORD="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --local-dir) LOCAL_DIR="$2"; shift 2 ;;
    --run-as-root) RUN_AS_ROOT="true"; shift ;;
    --no-service) NO_SERVICE="true"; shift ;;
    --behind-proxy) BEHIND_PROXY="true"; shift ;;
    --ui-host) UI_HOST="$2"; shift 2 ;;
    --ui-port) UI_PORT="$2"; shift 2 ;;
    --public-ui) PUBLIC_UI="true"; shift ;;
    --no-start) START="false"; shift ;;
    --no-verify) VERIFY="false"; shift ;;
    --purge) PURGE="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage; die "未知参数：$1" ;;
  esac
done

VERSION="${VERSION#v}"
[[ "$ROLE" == "server" || "$ROLE" == "client" ]] || die "--role 必须是 server 或 client"
if [[ -n "$DOMAIN" && ! "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]; then
  die "--domain 不是有效域名：$DOMAIN"
fi
if [[ "$BEHIND_PROXY" == "true" && "$PUBLIC_UI" == "true" ]]; then
  die "--behind-proxy 与 --public-ui 互斥：前者由 Nginx 终止 TLS，后者由 Ostium 自己监听 TLS"
fi
if [[ "$PUBLIC_UI" == "true" ]]; then
  die "--public-ui 需要已有证书和 TOTP，不能在安装阶段启用；请先本地安装，登录后在 Settings 中开启"
fi
if [[ "$ACTION" == "status" ]]; then
  detect_platform
  show_status
  exit 0
fi
need_root
detect_platform
validate_install_path "$PREFIX" "安装目录"
validate_install_path "$DATA" "数据目录"
validate_install_path "$CONFIG" "配置目录"
validate_install_path "$CLIENT_DATA" "客户端核心数据目录"
validate_install_path "$CLIENT_UI_DATA" "客户端 UI 数据目录"
validate_install_path "$BIN_LINK" "可执行链接"
validate_install_path "$SYSTEMD_DIR" "systemd 目录"

if [[ "$ACTION" == "uninstall" ]]; then
  uninstall_ostium
  exit 0
fi

if [[ "$ACTION" == "upgrade" && -z "$LOCAL_DIR" ]]; then
  [[ -d "$PREFIX" ]] || die "未发现 $PREFIX，无法升级；请先安装"
fi
if [[ -z "$PASSWORD" && "$ACTION" == "install" && "$ROLE" == "server" ]]; then
  PASSWORD="$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 24)"
fi

ensure_tools
resolve_version
download_release
bootstrap_python
detect_existing_mode
run_platform_installer

if [[ "$ACTION" == "install" && -n "$PASSWORD" && "$ROLE" == "server" ]]; then
  if [[ "$BEHIND_PROXY" == "true" ]]; then
    ADMIN_URL="https://${DOMAIN:-your-domain} （Nginx/Caddy 反代到 127.0.0.1:${UI_PORT:-8443}）"
  else
    ADMIN_URL="http://127.0.0.1:${UI_PORT:-8443} （建议 SSH 隧道）"
  fi
  cat <<EOF

============================================================
Ostium 安装完成
============================================================
  管理地址：$ADMIN_URL
  管理密码：$PASSWORD
  安装目录：$PREFIX
  运行身份：$([[ "$RUN_AS_ROOT" == "true" ]] && echo root || echo "无特权服务用户")
  服务管理：$([[ "$NO_SERVICE" == "true" ]] && echo "未注册，交给你的进程管理器" || echo systemd/launchd)
============================================================
密码只显示一次。登录后请立即修改密码并启用 TOTP。
EOF
elif [[ "$ACTION" == "install" && "$ROLE" == "client" ]]; then
  cat <<EOF

============================================================
Ostium 客户端安装完成
============================================================
  Web UI：http://127.0.0.1:8787
  安装目录：$PREFIX
  运行身份：$([[ "$RUN_AS_ROOT" == "true" ]] && echo root || echo "无特权服务用户")
  服务管理：$([[ "$NO_SERVICE" == "true" ]] && echo "未注册，交给你的进程管理器" || echo systemd/launchd)
============================================================
首次打开 UI 会进入客户端设置向导，请在那里创建管理员账号并导入订阅。
EOF
else
  say "操作完成：$ACTION"
fi
