#!/usr/bin/env bash
# Ostium Server installer for Linux + systemd.
set -euo pipefail

VERSION="0.2.11"
RELEASE_VERSION="${OSTIUM_RELEASE_VERSION:-$VERSION}"
SINGBOX_VERSION="1.14.4"
SINGBOX_TAGS="with_quic,with_utls,with_clash_api,with_v2ray_api,badlinkname,tfogo_checklinkname0"
GO_VERSION="1.27.4"
GO_SHA256_AMD64="7226736c2339719cda28fbf3a54d71aa63bcefe376e98cef00034268dab24840"
GO_SHA256_ARM64="3392582988a273a87ab5043ee1b2c9c17a2c3c00580bf9326c47a2e0aaaeac92"
UV_VERSION="0.11.14"
PREFIX="/opt/ostium"
# Root's PATH may contain a uv-managed or distro Python under /root, which the
# unprivileged ostium user cannot execute. Force the interpreter we install
# under /opt/ostium and keep uv's executable links out of /root.
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$PREFIX/python}"
export UV_PYTHON_BIN_DIR="${UV_PYTHON_BIN_DIR:-$PREFIX/bin}"
export UV_PYTHON_PREFERENCE="${UV_PYTHON_PREFERENCE:-only-managed}"
CONF_DIR="/etc/ostium"
DATA_DIR="/var/lib/ostium"
SERVICE_USER="ostium"
DOMAIN=""
WITH_CADDY=0
NO_SERVICE=0
FROM_SOURCE=0
PURGE=0
MODE="install"
SINGBOX_PATH=""
SOURCE_REF="${OSTIUM_SOURCE_REF:-main}"
SOURCE_URL="${OSTIUM_SOURCE_URL:-}"
SOURCE_TMP=""
PYPI=0
PYPI_VERSION="${OSTIUM_PYPI_VERSION:-}"
RELEASE_WHEEL=""
RELEASE_SINGBOX=""

usage() {
  cat <<'EOF'
Usage: install.sh [install|upgrade|uninstall] [options]

Options:
  --domain DOMAIN      Public hostname; configures Caddy and subscription URLs
  --with-caddy         Install and configure Caddy on 8443
  --no-service         Prepare files but do not enable systemd units
  --version VERSION    Release version to install (default: 0.2.11)
  --from-source        Build/install from source instead of release assets
  --wheel PATH         Install a specific wheel
  --pypi               Install ostium-ctl from PyPI (requires a published release)
  --ref REF            Source ref for --from-source (default: main)
  --source-url URL     Source tarball URL for --from-source
  --singbox PATH       Use a local sing-box binary instead of downloading
  --purge              With uninstall: delete data, config and the service user
  -h, --help           Show this help
EOF
}

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    install|upgrade|uninstall) MODE="$1" ;;
    --domain) DOMAIN="${2:?}"; shift ;;
    --with-caddy) WITH_CADDY=1 ;;
    --no-service) NO_SERVICE=1 ;;
    --version) RELEASE_VERSION="${2:?}"; shift ;;
    --from-source) FROM_SOURCE=1 ;;
    --wheel) WHEEL="${2:?}"; shift ;;
    --pypi) PYPI=1 ;;
    --ref) SOURCE_REF="${2:?}"; FROM_SOURCE=1; shift ;;
    --source-url) SOURCE_URL="${2:?}"; FROM_SOURCE=1; shift ;;
    --singbox) SINGBOX_PATH="${2:?}"; shift ;;
    --purge) PURGE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
  shift
done

PYPI_VERSION="${PYPI_VERSION:-$RELEASE_VERSION}"

[ "$(id -u)" -eq 0 ] || die "Run as root."
if [ -n "$DOMAIN" ]; then
  case "$DOMAIN" in
    *://*|*/*|*" "*|*..*|*.-*|*-.*)
      die "--domain must be a bare hostname such as vpn.example.com."
      ;;
  esac
  if ! printf '%s' "$DOMAIN" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$'; then
    die "--domain must be a bare hostname such as vpn.example.com."
  fi
fi
case "$(uname -m)" in
  x86_64|amd64) ARCH="amd64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  *) die "Unsupported architecture: $(uname -m) (Linux amd64/arm64 only)." ;;
esac
command -v systemctl >/dev/null || die "systemd is required (use Docker Compose otherwise)."
command -v apt-get >/dev/null || warn "Only apt-based distributions are automated; install curl/openssl/certbot manually if needed."
if [ "$PYPI" -eq 1 ] && [ -n "${WHEEL:-}" ]; then
  die "--pypi and --wheel cannot be used together."
fi
if [ "$PYPI" -eq 1 ] && [ "$FROM_SOURCE" -eq 1 ]; then
  die "--pypi and --from-source cannot be used together."
fi
if [ -n "${WHEEL:-}" ] && [ "$FROM_SOURCE" -eq 1 ]; then
  die "--wheel and --from-source cannot be used together."
fi
if [ "$PURGE" -eq 1 ] && [ "$MODE" != "uninstall" ]; then
  die "--purge is only valid with the uninstall command."
fi
if [ "$WITH_CADDY" -eq 1 ]; then
  [ -n "$DOMAIN" ] || die "--with-caddy requires --domain."
  command -v caddy >/dev/null || die "Install caddy first: https://caddyserver.com/docs/install"
  command -v certbot >/dev/null || die "Install certbot first."
fi

# A piped invocation has no script path. Keep ROOT empty; the release-asset or
# source preparation step will populate it instead of trusting the cwd.
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
  ROOT=""
fi

install_packages() {
  if command -v apt-get >/dev/null; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ca-certificates curl openssl git tar
  fi
}

prepare_release_assets() {
  # Production installs use the immutable GitHub Release assets: wheel, sdist
  # (for systemd/Caddy/certbot files) and the pinned sing-box binary.
  [ -n "$SOURCE_TMP" ] && return
  command -v curl >/dev/null || die "curl is required for online installation."
  command -v tar >/dev/null || die "tar is required for online installation."
  command -v sha256sum >/dev/null || die "sha256sum is required for release verification."
  local base wheel sdist asset
  base="${OSTIUM_RELEASE_BASE:-https://github.com/ThzxxArt/Ostium/releases/download/v${RELEASE_VERSION}}"
  base="${base%/}"
  wheel="ostium_ctl-${RELEASE_VERSION}-py3-none-any.whl"
  sdist="ostium_ctl-${RELEASE_VERSION}.tar.gz"
  SOURCE_TMP="$(mktemp -d)"
  trap 'rm -rf "$SOURCE_TMP"' EXIT
  log "Downloading Ostium ${RELEASE_VERSION} release assets"
  for asset in "$wheel" "$sdist" sing-box SHA256SUMS; do
    curl -fsSL --retry 5 "$base/$asset" -o "$SOURCE_TMP/$asset" \
      || die "Could not download release asset: $base/$asset"
  done
  (cd "$SOURCE_TMP" && sha256sum -c --ignore-missing SHA256SUMS) \
    || die "Release asset checksum verification failed."
  tar -xzf "$SOURCE_TMP/$sdist" -C "$SOURCE_TMP"
  ROOT="$(find "$SOURCE_TMP" -maxdepth 1 -mindepth 1 -type d | head -n 1)"
  if [ ! -f "$ROOT/pyproject.toml" ] || [ ! -d "$ROOT/deploy/systemd" ]; then
    die "Downloaded release sdist is missing deployment assets."
  fi
  RELEASE_WHEEL="$SOURCE_TMP/$wheel"
  RELEASE_SINGBOX="$SOURCE_TMP/sing-box"
  chmod 0755 "$RELEASE_SINGBOX"
}

prepare_source() {
  # --from-source keeps the development workflow: download a source ref and
  # build sing-box locally. It is never the default production path.
  if [ -n "$ROOT" ] && [ -f "$ROOT/pyproject.toml" ] && [ -d "$ROOT/src/ostium/config" ]; then
    return
  fi
  [ -n "$SOURCE_TMP" ] && return
  command -v curl >/dev/null || die "curl is required for online installation."
  command -v tar >/dev/null || die "tar is required for online installation."
  local url kind
  if [ -n "$SOURCE_URL" ]; then
    url="$SOURCE_URL"
  else
    case "$SOURCE_REF" in
      v*) kind="tags" ;;
      *) kind="heads" ;;
    esac
    url="https://github.com/ThzxxArt/Ostium/archive/refs/${kind}/${SOURCE_REF}.tar.gz"
  fi
  SOURCE_TMP="$(mktemp -d)"
  trap 'rm -rf "$SOURCE_TMP"' EXIT
  log "Downloading Ostium source (${SOURCE_REF})"
  curl -fsSL --retry 5 "$url" -o "$SOURCE_TMP/source.tar.gz" || die "Could not download $url"
  tar -xzf "$SOURCE_TMP/source.tar.gz" -C "$SOURCE_TMP"
  ROOT="$(find "$SOURCE_TMP" -maxdepth 1 -mindepth 1 -type d | head -n 1)"
  if [ ! -f "$ROOT/pyproject.toml" ] || [ ! -d "$ROOT/src/ostium" ]; then
    die "Downloaded source is not a valid Ostium checkout."
  fi
}

create_user() {
  if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  fi
  install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" "$DATA_DIR" "$DATA_DIR/runtime" "$DATA_DIR/certs" "$DATA_DIR/logs" "$DATA_DIR/backups" "$DATA_DIR/imports"
  # Traversable by the caddy user so it can read /etc/ostium/tls, while the
  # environment file itself remains 0640 root:ostium.
  install -d -m 0751 -o root -g "$SERVICE_USER" "$CONF_DIR"
}

write_env() {
  local env_file="$CONF_DIR/ostium.env"
  if [ -f "$env_file" ] && [ "$MODE" = "install" ]; then
    warn "$env_file already exists; keeping it"
    return
  fi
  local secret field allowed old_umask
  secret="$(openssl rand -base64 48 | tr -d '\n')"
  field="$(openssl rand -base64 32 | tr -d '\n')"
  allowed="localhost,127.0.0.1,[::1]"
  if [ -n "$DOMAIN" ]; then allowed="$DOMAIN,$allowed"; fi
  old_umask="$(umask)"
  umask 077
  cat >"$env_file" <<EOF
DJANGO_SETTINGS_MODULE=ostium.config.settings.prod
OSTIUM_SECRET_KEY=$secret
OSTIUM_FIELD_KEY=$field
OSTIUM_DATA_DIR=$DATA_DIR
OSTIUM_DB_URL=sqlite:///$DATA_DIR/ostium.db
OSTIUM_ALLOWED_HOSTS=$allowed
OSTIUM_CSRF_TRUSTED_ORIGINS=${DOMAIN:+https://$DOMAIN:8443}
OSTIUM_PUBLIC_BASE_URL=${DOMAIN:+https://$DOMAIN:8443}
OSTIUM_BEHIND_PROXY=$([ -n "$DOMAIN" ] && echo true || echo false)
OSTIUM_SECURE_COOKIES=$([ -n "$DOMAIN" ] && echo true || echo false)
OSTIUM_REQUIRE_TOTP=$([ -n "$DOMAIN" ] && echo true || echo false)
OSTIUM_SINGBOX_PATH=$PREFIX/core/sing-box
OSTIUM_LOG_LEVEL=INFO
OSTIUM_DOMAIN=$DOMAIN
OSTIUM_ACME_EMAIL=${DOMAIN:+admin@$DOMAIN}
EOF
  chown root:"$SERVICE_USER" "$env_file"
  chmod 0640 "$env_file"
  umask "$old_umask"
}

install_uv() {
  if ! command -v uv >/dev/null; then
    log "Installing uv ${UV_VERSION}"
    curl -LsSf --retry 5 https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_VERSION="$UV_VERSION" sh
  fi
  install -d -m 0755 "$PREFIX" "$PREFIX/bin"
  uv python install 3.14
  chmod -R a+rX "$UV_PYTHON_INSTALL_DIR" "$PREFIX/bin" 2>/dev/null || true
}

install_app() {
  local python_real python_root
  install -d -m 0755 "$PREFIX" "$PREFIX/core"
  if [ ! -x "$PREFIX/venv/bin/python" ] || [ "$MODE" = "upgrade" ]; then
    log "Creating Python environment"
    uv venv --python 3.14 --clear "$PREFIX/venv"
  fi
  python_root="$(readlink -f "$UV_PYTHON_INSTALL_DIR")"
  python_real="$(readlink -f "$PREFIX/venv/bin/python")"
  case "$python_real" in
    "$python_root"/*) ;;
    *)
      warn "Existing venv uses $python_real; recreating it with the managed Python"
      uv venv --python 3.14 --clear "$PREFIX/venv"
      python_real="$(readlink -f "$PREFIX/venv/bin/python")"
      ;;
  esac
  case "$python_real" in
    "$python_root"/*) ;;
    *) die "The venv Python resolves outside $python_root: $python_real" ;;
  esac
  chmod -R a+rX "$PREFIX/venv" 2>/dev/null || true
  if [ "$PYPI" -eq 1 ]; then
    uv pip install --python "$PREFIX/venv/bin/python" "ostium-ctl==${PYPI_VERSION}"
  elif [ -n "${WHEEL:-}" ]; then
    uv pip install --python "$PREFIX/venv/bin/python" "$WHEEL"
  elif [ -n "${RELEASE_WHEEL:-}" ]; then
    uv pip install --python "$PREFIX/venv/bin/python" "$RELEASE_WHEEL"
  elif [ "$FROM_SOURCE" -eq 1 ] || { [ -n "$ROOT" ] && [ -f "$ROOT/pyproject.toml" ]; }; then
    uv pip install --python "$PREFIX/venv/bin/python" "$ROOT"
  else
    die "No wheel supplied. Use the release assets, --wheel, or --from-source."
  fi
  # Packages created by uv inherit the caller's umask. Normalize again after
  # installation so the service user can read every module.
  chmod -R a+rX "$PREFIX/venv" "$UV_PYTHON_INSTALL_DIR" 2>/dev/null || true
  runuser -u "$SERVICE_USER" -- "$PREFIX/venv/bin/python" -V >/dev/null \
    || die "The virtualenv Python is not readable by $SERVICE_USER (check $PREFIX/python permissions)."
}

singbox_binary_ok() {
  local binary="$1"
  [ -x "$binary" ] || return 1
  "$binary" version 2>/dev/null | grep -q "with_v2ray_api"
}

singbox_version_ok() {
  local binary="$1"
  [ -x "$binary" ] || return 1
  "$binary" version 2>/dev/null | grep -q "version v${SINGBOX_VERSION}\$"
}

record_singbox_digest() {
  local target="$1"
  local digest
  digest="$(sha256sum "$target" | awk '{print $1}')"
  printf '%s  %s\n' "$digest" "$(basename "$target")" >"$PREFIX/core/sing-box.sha256"
  cat >"$PREFIX/core/sing-box.sbom.json" <<EOF
{"component":"sing-box","version":"v${SINGBOX_VERSION}","source":"https://github.com/SagerNet/sing-box","build_tags":"${SINGBOX_TAGS}","platform":"linux-${ARCH}","sha256":"${digest}"}
EOF
  if [ -f "$CONF_DIR/ostium.env" ]; then
    if grep -q '^OSTIUM_SINGBOX_BINARY_SHA256=' "$CONF_DIR/ostium.env"; then
      sed -i "s|^OSTIUM_SINGBOX_BINARY_SHA256=.*|OSTIUM_SINGBOX_BINARY_SHA256=${digest}|" "$CONF_DIR/ostium.env"
    else
      printf 'OSTIUM_SINGBOX_BINARY_SHA256=%s\n' "$digest" >>"$CONF_DIR/ostium.env"
    fi
  fi
  log "sing-box SHA256: ${digest}"
}

go_version_ok() {
  local version major minor
  version="$("$1" env GOVERSION 2>/dev/null | sed 's/^go//')"
  major="${version%%.*}"
  minor="${version#*.}"
  minor="${minor%%.*}"
  case "$major" in ''|*[!0-9]*) return 1 ;; esac
  case "$minor" in ''|*[!0-9]*) return 1 ;; esac
  [ "$major" -gt 1 ] || { [ "$major" -eq 1 ] && [ "$minor" -ge 24 ]; }
}

install_go() {
  if command -v go >/dev/null && go_version_ok "$(command -v go)"; then
    GO_BIN="$(command -v go)"
    return
  fi
  local tmp url expected
  tmp="$(mktemp -d)"
  url="https://go.dev/dl/go${GO_VERSION}.linux-${ARCH}.tar.gz"
  case "$ARCH" in
    amd64) expected="${GO_SHA256_AMD64}" ;;
    arm64) expected="${GO_SHA256_ARM64}" ;;
  esac
  if [ -n "${GO_SHA256:-}" ]; then
    expected="$GO_SHA256"
  fi
  [ -n "$expected" ] || die "No Go SHA256 configured for ${ARCH}; set GO_SHA256 to override."
  log "Downloading Go ${GO_VERSION} for ${ARCH}"
  curl -fsSL --retry 5 -o "$tmp/go.tar.gz" "$url"
  (cd "$tmp" && echo "${expected}  go.tar.gz" | sha256sum -c -)
  tar -xzf "$tmp/go.tar.gz" -C "$tmp"
  GO_BIN="$tmp/go/bin/go"
  GO_TMP="$tmp"
}

install_singbox() {
  local target="$PREFIX/core/sing-box"
  if [ "$MODE" = "upgrade" ] && singbox_binary_ok "$target" && singbox_version_ok "$target"; then
    log "Keeping existing sing-box v${SINGBOX_VERSION} with with_v2ray_api"
    record_singbox_digest "$target"
    return
  fi
  if [ -n "$SINGBOX_PATH" ]; then
    install -m 0755 "$SINGBOX_PATH" "$target"
    if ! singbox_binary_ok "$target"; then
      die "--singbox binary was not built with with_v2ray_api; traffic statistics would be unavailable."
    fi
    record_singbox_digest "$target"
    return
  fi
  if [ -n "${RELEASE_SINGBOX:-}" ]; then
    log "Installing prebuilt sing-box v${SINGBOX_VERSION} from release assets"
    install -m 0755 "$RELEASE_SINGBOX" "$target"
    if ! singbox_binary_ok "$target"; then
      die "Release sing-box was not built with with_v2ray_api."
    fi
    if ! singbox_version_ok "$target"; then
      die "Release sing-box version does not match v${SINGBOX_VERSION}."
    fi
    record_singbox_digest "$target"
    return
  fi
  if [ -n "${OSTIUM_SINGBOX_BINARY_URL:-}" ]; then
    log "Downloading custom sing-box binary"
    curl -fsSL --retry 5 -o "$target" "$OSTIUM_SINGBOX_BINARY_URL"
    chmod 0755 "$target"
    if ! singbox_binary_ok "$target"; then
      die "OSTIUM_SINGBOX_BINARY_URL does not provide with_v2ray_api."
    fi
    record_singbox_digest "$target"
    return
  fi

  log "Building sing-box ${SINGBOX_VERSION} with statistics support"
  install_go
  local tmp
  tmp="$(mktemp -d)"
  git clone --depth 1 --branch "v${SINGBOX_VERSION}" https://github.com/SagerNet/sing-box.git "$tmp/src"
  (cd "$tmp/src" && CGO_ENABLED=0 GOOS=linux GOARCH="$ARCH" "$GO_BIN" build \
    -trimpath \
    -ldflags "-s -w -X github.com/sagernet/sing-box/constant.Version=v${SINGBOX_VERSION}" \
    -tags "$SINGBOX_TAGS" -o "$tmp/sing-box" ./cmd/sing-box)
  install -m 0755 "$tmp/sing-box" "$target"
  rm -rf "$tmp" "${GO_TMP:-}"
  if ! singbox_binary_ok "$target"; then
    die "sing-box build did not include with_v2ray_api."
  fi
  record_singbox_digest "$target"
}

run_as_ostium() {
  (
    set -a
    # shellcheck disable=SC1090,SC1091
    . "$CONF_DIR/ostium.env"
    set +a
    runuser -u "$SERVICE_USER" -- "$@"
  )
}

setup_app() {
  log "Applying migrations and static files"
  run_as_ostium "$PREFIX/venv/bin/ostium" migrate --noinput
  run_as_ostium "$PREFIX/venv/bin/ostium" collectstatic --noinput
  if ! run_as_ostium "$PREFIX/venv/bin/ostium" shell -c "from django.contrib.auth import get_user_model; raise SystemExit(0 if get_user_model().objects.exists() else 1)" >/dev/null 2>&1; then
    local password
    password="$(openssl rand -base64 24 | tr -d '\n/+=' | head -c 24)"
    log "Creating administrator"
    run_as_ostium "$PREFIX/venv/bin/ostium" init --username admin --password "$password" ${DOMAIN:+--domain "$DOMAIN"}
    echo
    printf '\033[1;32mInitial administrator password: %s\033[0m\n' "$password"
    echo "You must change it at first login."
    echo
  fi
}

install_wrapper() {
  cat >/usr/local/bin/ostium <<'EOF'
#!/bin/sh
set -a
. /etc/ostium/ostium.env
set +a
exec /opt/ostium/venv/bin/ostium "$@"
EOF
  chmod 0755 /usr/local/bin/ostium
}

install_units() {
  install -m 0644 "$ROOT/deploy/systemd/ostium-web.service" /etc/systemd/system/
  install -m 0644 "$ROOT/deploy/systemd/ostium-worker.service" /etc/systemd/system/
  install -m 0644 "$ROOT/deploy/systemd/ostium-jobs.service" /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable ostium-web.service ostium-worker.service ostium-jobs.service
  systemctl restart ostium-web.service ostium-worker.service ostium-jobs.service
}

setup_caddy() {
  [ -n "$DOMAIN" ] || die "--with-caddy requires --domain."
  command -v caddy >/dev/null || die "Install caddy first: https://caddyserver.com/docs/install"
  command -v certbot >/dev/null || die "Install certbot first."
  install -d -m 0755 /var/www/certbot
  if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
    log "Requesting certificate with certbot"
    systemctl stop caddy 2>/dev/null || true
    certbot certonly --standalone -d "$DOMAIN" --agree-tos --non-interactive \
      -m "${OSTIUM_ACME_EMAIL:-admin@$DOMAIN}" || warn "certbot failed; configure DNS and retry."
  fi
  if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ] || [ ! -f "/etc/letsencrypt/live/$DOMAIN/privkey.pem" ]; then
    die "No certificate found for $DOMAIN. Fix DNS/port 80, then rerun with --with-caddy."
  fi
  install -d -m 0750 -o root -g caddy "/etc/ostium/tls/$DOMAIN"
  install -m 0640 -o root -g caddy "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" \
    "/etc/ostium/tls/$DOMAIN/fullchain.pem"
  install -m 0640 -o root -g caddy "/etc/letsencrypt/live/$DOMAIN/privkey.pem" \
    "/etc/ostium/tls/$DOMAIN/privkey.pem"
  install -d -m 0755 /etc/systemd/system/caddy.service.d
  cat >/etc/systemd/system/caddy.service.d/ostium.conf <<EOF
[Service]
EnvironmentFile=/etc/ostium/ostium.env
EOF
  install -m 0644 "$ROOT/deploy/caddy/Caddyfile.example" /etc/caddy/Caddyfile
  systemctl daemon-reload
  systemctl enable --now caddy
  install -d -m 0755 /etc/letsencrypt/renewal-hooks/{pre,deploy,post}
  install -m 0755 "$ROOT/deploy/certbot/deploy-hook.sh" /etc/letsencrypt/renewal-hooks/deploy/ostium.sh
  install -m 0755 "$ROOT/deploy/certbot/pre-hook.sh" /etc/letsencrypt/renewal-hooks/pre/ostium-stop-caddy.sh
  install -m 0755 "$ROOT/deploy/certbot/post-hook.sh" /etc/letsencrypt/renewal-hooks/post/ostium-start-caddy.sh
  # Import certificates that already existed before this installation, not
  # only certificates renewed after the hook was installed.
  if [ -x /etc/letsencrypt/renewal-hooks/deploy/ostium.sh ]; then
    /etc/letsencrypt/renewal-hooks/deploy/ostium.sh \
      || warn "Existing certbot certificates could not be imported; use Certificates -> Sync certbot."
  fi
  systemctl enable --now certbot.timer 2>/dev/null || warn "certbot.timer could not be enabled."
  certbot renew --dry-run >/dev/null 2>&1 || warn "certbot renew --dry-run failed; check hooks and port 80."
  log "Caddy is serving https://$DOMAIN:8443"
}

health_check() {
  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then
      log "Management plane is healthy"
      return 0
    fi
    sleep 2
  done
  die "Management plane did not become healthy on 127.0.0.1:8000."
}

do_install() {
  install_packages
  if [ "$FROM_SOURCE" -eq 1 ]; then
    prepare_source
  else
    prepare_release_assets
  fi
  create_user
  write_env
  install_uv
  install_app
  install_singbox
  install_wrapper
  setup_app
  if [ "$NO_SERVICE" -eq 0 ]; then
    install_units
    [ "$WITH_CADDY" -eq 1 ] && setup_caddy
    health_check
  fi
  echo
  log "Ostium ${RELEASE_VERSION} installed."
  echo "  Console (loopback): http://127.0.0.1:8000/"
  echo "  SSH tunnel:         ssh -L 8000:127.0.0.1:8000 user@server"
  echo "  Enable TOTP at:     http://127.0.0.1:8000/accounts/totp/setup/"
}

do_upgrade() {
  install_packages
  [ -f "$CONF_DIR/ostium.env" ] || die "No existing installation found at $CONF_DIR/ostium.env."
  install_uv
  if grep -q '^OSTIUM_BACKUP_PASSWORD=..' "$CONF_DIR/ostium.env"; then
    log "Creating a pre-upgrade backup"
    run_as_ostium "$PREFIX/venv/bin/ostium" backup create --note "pre-upgrade" || die "Pre-upgrade backup failed."
  else
    warn "OSTIUM_BACKUP_PASSWORD is not set; skipping the automatic pre-upgrade backup."
  fi
  if [ "$FROM_SOURCE" -eq 1 ]; then
    prepare_source
  else
    prepare_release_assets
  fi
  install_app
  install_singbox
  run_as_ostium "$PREFIX/venv/bin/ostium" migrate --noinput
  run_as_ostium "$PREFIX/venv/bin/ostium" collectstatic --noinput
  if [ -x /etc/letsencrypt/renewal-hooks/deploy/ostium.sh ]; then
    /etc/letsencrypt/renewal-hooks/deploy/ostium.sh \
      || warn "Existing certbot certificates could not be imported; use Certificates -> Sync certbot."
  fi
  systemctl restart ostium-web.service ostium-worker.service ostium-jobs.service
  health_check
  log "Upgrade complete."
}

do_uninstall() {
  systemctl disable --now ostium-web.service ostium-worker.service ostium-jobs.service 2>/dev/null || true
  rm -f /etc/systemd/system/ostium-{web,worker,jobs}.service /usr/local/bin/ostium
  rm -f /etc/systemd/system/caddy.service.d/ostium.conf
  rm -f /etc/letsencrypt/renewal-hooks/deploy/ostium.sh \
    /etc/letsencrypt/renewal-hooks/pre/ostium-stop-caddy.sh \
    /etc/letsencrypt/renewal-hooks/post/ostium-start-caddy.sh
  systemctl daemon-reload
  if [ "$PURGE" -eq 1 ]; then
    warn "Purging data, certificates and configuration"
    rm -rf "$DATA_DIR" "$CONF_DIR" "$PREFIX"
    userdel "$SERVICE_USER" 2>/dev/null || true
  else
    log "Services removed; data kept in $DATA_DIR and $CONF_DIR."
  fi
}

case "$MODE" in
  install) do_install ;;
  upgrade) do_upgrade ;;
  uninstall) do_uninstall ;;
esac
