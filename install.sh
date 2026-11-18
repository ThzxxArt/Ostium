#!/usr/bin/env bash
# Ostium Server installer for Linux + systemd.
set -euo pipefail

VERSION="0.2.0"
SINGBOX_VERSION="1.14.4"
PREFIX="/opt/ostium"
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

usage() {
  cat <<'EOF'
Usage: install.sh [install|upgrade|uninstall] [options]

Options:
  --domain DOMAIN      Public hostname; configures Caddy and subscription URLs
  --with-caddy         Install and configure Caddy on 8443
  --no-service         Prepare files but do not enable systemd units
  --from-source        Install this checkout instead of a release wheel
  --wheel PATH         Install a specific wheel
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
    --from-source) FROM_SOURCE=1 ;;
    --wheel) WHEEL="${2:?}"; shift ;;
    --singbox) SINGBOX_PATH="${2:?}"; shift ;;
    --purge) PURGE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
  shift
done

[ "$(id -u)" -eq 0 ] || die "Run as root."
command -v systemctl >/dev/null || die "systemd is required (use Docker Compose otherwise)."
command -v apt-get >/dev/null || warn "Only apt-based distributions are automated; install curl/openssl/certbot manually if needed."

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

install_packages() {
  if command -v apt-get >/dev/null; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ca-certificates curl openssl
  fi
}

create_user() {
  if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  fi
  install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" "$DATA_DIR" "$DATA_DIR/runtime" "$DATA_DIR/certs" "$DATA_DIR/logs" "$DATA_DIR/backups" "$DATA_DIR/imports"
  install -d -m 0750 -o root -g "$SERVICE_USER" "$CONF_DIR"
}

write_env() {
  local env_file="$CONF_DIR/ostium.env"
  if [ -f "$env_file" ] && [ "$MODE" = "install" ]; then
    warn "$env_file already exists; keeping it"
    return
  fi
  local secret field allowed
  secret="$(openssl rand -base64 48 | tr -d '\n')"
  field="$(openssl rand -base64 32 | tr -d '\n')"
  allowed="localhost,127.0.0.1,[::1]"
  if [ -n "$DOMAIN" ]; then allowed="$DOMAIN,$allowed"; fi
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
EOF
  chown root:"$SERVICE_USER" "$env_file"
  chmod 0640 "$env_file"
}

install_uv() {
  if ! command -v uv >/dev/null; then
    log "Installing uv"
    curl -LsSf --retry 5 https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
  fi
  uv python install 3.14
}

install_app() {
  install -d -m 0755 "$PREFIX" "$PREFIX/core"
  if [ ! -x "$PREFIX/venv/bin/python" ] || [ "$MODE" = "upgrade" ]; then
    log "Creating Python environment"
    uv venv --python 3.14 --clear "$PREFIX/venv"
  fi
  if [ -n "${WHEEL:-}" ]; then
    uv pip install --python "$PREFIX/venv/bin/python" "$WHEEL"
  elif [ "$FROM_SOURCE" -eq 1 ] || [ -f "$ROOT/pyproject.toml" ]; then
    uv pip install --python "$PREFIX/venv/bin/python" "$ROOT"
  else
    die "No wheel supplied. Use --wheel, --from-source, or run from the repository."
  fi
}

install_singbox() {
  local target="$PREFIX/core/sing-box"
  if [ "$MODE" = "upgrade" ] && [ -x "$target" ]; then
    return
  fi
  if [ -n "$SINGBOX_PATH" ]; then
    install -m 0755 "$SINGBOX_PATH" "$target"
    return
  fi
  local tmp
  tmp="$(mktemp -d)"
  log "Downloading sing-box ${SINGBOX_VERSION}"
  curl -fsSL --retry 5 -o "$tmp/sing-box.tar.gz" \
    "https://github.com/SagerNet/sing-box/releases/download/v${SINGBOX_VERSION}/sing-box-${SINGBOX_VERSION}-linux-amd64.tar.gz"
  tar -xzf "$tmp/sing-box.tar.gz" -C "$tmp"
  install -m 0755 "$tmp/sing-box-${SINGBOX_VERSION}-linux-amd64/sing-box" "$target"
  if [ -n "${OSTIUM_SINGBOX_SHA256:-}" ]; then
    echo "${OSTIUM_SINGBOX_SHA256}  $target" | sha256sum -c -
  else
    warn "OSTIUM_SINGBOX_SHA256 is not set; pin it in production."
  fi
  rm -rf "$tmp"
}

run_as_ostium() {
  runuser -u "$SERVICE_USER" -- env $(grep -v '^#' "$CONF_DIR/ostium.env" | xargs) "$@"
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
    certbot certonly --standalone -d "$DOMAIN" --agree-tos --non-interactive -m "admin@$DOMAIN" || warn "certbot failed; configure DNS and retry."
  fi
  install -d -m 0755 /etc/systemd/system/caddy.service.d
  cat >/etc/systemd/system/caddy.service.d/ostium.conf <<EOF
[Service]
EnvironmentFile=/etc/ostium/ostium.env
EOF
  install -m 0644 "$ROOT/deploy/caddy/Caddyfile.example" /etc/caddy/Caddyfile
  systemctl daemon-reload
  systemctl enable --now caddy
  install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
  install -m 0755 "$ROOT/deploy/certbot/deploy-hook.sh" /etc/letsencrypt/renewal-hooks/deploy/ostium.sh
  log "Caddy is serving https://$DOMAIN:8443"
}

health_check() {
  sleep 3
  if command -v curl >/dev/null; then
    curl -fsS http://127.0.0.1:8000/healthz >/dev/null && log "Management plane is healthy"
  fi
}

do_install() {
  install_packages
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
  log "Ostium ${VERSION} installed."
  echo "  Console (loopback): http://127.0.0.1:8000/"
  echo "  SSH tunnel:         ssh -L 8000:127.0.0.1:8000 user@server"
  echo "  Enable TOTP at:     http://127.0.0.1:8000/accounts/totp/setup/"
}

do_upgrade() {
  install_packages
  install_uv
  install_app
  install_singbox
  run_as_ostium "$PREFIX/venv/bin/ostium" migrate --noinput
  run_as_ostium "$PREFIX/venv/bin/ostium" collectstatic --noinput
  systemctl restart ostium-web.service ostium-worker.service ostium-jobs.service
  health_check
  log "Upgrade complete."
}

do_uninstall() {
  systemctl disable --now ostium-web.service ostium-worker.service ostium-jobs.service 2>/dev/null || true
  rm -f /etc/systemd/system/ostium-{web,worker,jobs}.service /usr/local/bin/ostium
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
