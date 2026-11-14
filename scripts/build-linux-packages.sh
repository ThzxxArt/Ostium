#!/usr/bin/env bash
# Build native Linux DEB and AppImage packages for one architecture.
#
# The script expects a PyInstaller one-dir bundle at dist/Ostium and a pinned
# core archive.  Run it on the target architecture so both artefacts contain
# the correct ELF binaries.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="0.1.1"
ARCH="amd64"
CORE=""
OUT="$ROOT/dist/packages"
APP="$ROOT/dist/Ostium"
SKIP_APPIMAGE="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --arch) ARCH="$2"; shift 2 ;;
    --core) CORE="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --skip-appimage) SKIP_APPIMAGE="true"; shift ;;
    -h|--help)
      echo "usage: $0 --version 0.1.1 --arch amd64 --core ostium-core-*.tar.gz [--out DIR] [--skip-appimage]"
      exit 0
      ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Release tags are v0.1.1; Debian versions and filenames must be 0.1.1.
VERSION="${VERSION#v}"

if [[ ! -x "$APP/ostium" ]]; then
  echo "missing PyInstaller bundle: $APP/ostium" >&2
  exit 2
fi
if [[ -z "$CORE" || ! -f "$CORE" ]]; then
  echo "--core is required" >&2
  exit 2
fi
if [[ "$ARCH" != "amd64" && "$ARCH" != "arm64" ]]; then
  echo "--arch must be amd64 or arm64" >&2
  exit 2
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
tar -xzf "$CORE" -C "$WORK" --no-same-owner
if [[ ! -x "$WORK/sing-box" ]]; then
  echo "core archive does not contain sing-box" >&2
  exit 2
fi
mkdir -p "$OUT"

DEB_ARCH="amd64"
[[ "$ARCH" == "arm64" ]] && DEB_ARCH="arm64"

build_deb() {
  local root="$WORK/deb"
  mkdir -p "$root/DEBIAN" "$root/opt/ostium" "$root/usr/bin" "$root/usr/lib/systemd/system" \
    "$root/usr/share/doc/ostium" "$root/usr/share/licenses/ostium"
  cp -a "$APP" "$root/opt/ostium/app"
  chmod -R u+rwX,go+rX,go-w "$root/opt/ostium/app"
  install -d -m 0755 "$root/opt/ostium/core"
  install -m 0755 "$WORK/sing-box" "$root/opt/ostium/core/sing-box"
  if [[ -f "$WORK/LICENSE" ]]; then install -m 0644 "$WORK/LICENSE" "$root/usr/share/licenses/ostium/sing-box-LICENSE"; fi
  if [[ -f "$WORK/SBOM.txt" ]]; then
    install -m 0644 "$WORK/SBOM.txt" "$root/usr/share/doc/ostium/core-SBOM.txt"
    install -m 0644 "$WORK/SBOM.txt" "$root/opt/ostium/core/SBOM.txt"
  fi
  if [[ -f "$ROOT/LICENSE" ]]; then install -m 0644 "$ROOT/LICENSE" "$root/usr/share/doc/ostium/LICENSE"; fi
  if [[ -f "$ROOT/NOTICE" ]]; then install -m 0644 "$ROOT/NOTICE" "$root/usr/share/doc/ostium/NOTICE"; fi
  install -m 0644 "$ROOT/deploy/systemd/ostium.service" "$root/usr/lib/systemd/system/ostium.service"
  install -m 0644 "$ROOT/deploy/systemd/ostium-core.service" "$root/usr/lib/systemd/system/ostium-core.service"
  sed -i 's#/opt/ostium/venv/bin/ostium#/opt/ostium/app/ostium#g' \
    "$root/usr/lib/systemd/system/ostium.service" \
    "$root/usr/lib/systemd/system/ostium-core.service"
  ln -sfn /opt/ostium/app/ostium "$root/usr/bin/ostium"

  cat >"$root/DEBIAN/control" <<EOF
Package: ostium
Version: $VERSION
Section: net
Priority: optional
Architecture: $DEB_ARCH
Maintainer: Ostium Contributors <noreply@ostium.invalid>
Depends: ca-certificates, curl, adduser
Homepage: https://github.com/ThzxxArt/Ostium
Description: Ostium dual-role VPN and proxy console
 Ostium is a self-hosted VPN and universal proxy console built on sing-box.
 This package installs the control plane, the pinned core and systemd units.
EOF
  cat >"$root/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
getent group ostium >/dev/null 2>&1 || groupadd --system ostium
id -u ostium >/dev/null 2>&1 || adduser --system --ingroup ostium --home /var/lib/ostium --shell /usr/sbin/nologin ostium
install -d -m 0750 -o ostium -g ostium /var/lib/ostium /var/lib/ostium/runtime \
  /var/lib/ostium/logs /var/lib/ostium/backups /var/lib/ostium/certs \
  /var/lib/ostium/core /var/lib/ostium/state /var/lib/ostium/rulesets /etc/ostium
if [ ! -f /etc/ostium/config.toml ]; then
  cat >/etc/ostium/config.toml <<CONF
role = "server"
host = "127.0.0.1"
port = 8443
public_ui = false
allow_insecure_bind = false
data_dir = "/var/lib/ostium"
config_dir = "/etc/ostium"
log_level = "info"
core_url = "http://127.0.0.1:8788"
engine_version = "1.14.4-ostium.1"
engine_path = "/opt/ostium/core/sing-box"
CONF
  chmod 0600 /etc/ostium/config.toml
  chown ostium:ostium /etc/ostium/config.toml
fi
systemctl daemon-reload >/dev/null 2>&1 || true
systemctl enable ostium-core ostium >/dev/null 2>&1 || true
systemctl restart ostium-core ostium >/dev/null 2>&1 || true
exit 0
EOF
  cat >"$root/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
systemctl stop ostium ostium-core >/dev/null 2>&1 || true
systemctl disable ostium ostium-core >/dev/null 2>&1 || true
exit 0
EOF
  cat >"$root/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
systemctl daemon-reload >/dev/null 2>&1 || true
if [ "$1" = "purge" ]; then
  rm -rf /var/lib/ostium /etc/ostium
fi
exit 0
EOF
  chmod 0755 "$root/DEBIAN/postinst" "$root/DEBIAN/prerm" "$root/DEBIAN/postrm"
  if command -v fakeroot >/dev/null 2>&1; then
    fakeroot dpkg-deb --build --root-owner-group "$root" \
      "$OUT/ostium_${VERSION}_${DEB_ARCH}.deb"
  else
    dpkg-deb --build --root-owner-group "$root" "$OUT/ostium_${VERSION}_${DEB_ARCH}.deb"
  fi
  echo "built $OUT/ostium_${VERSION}_${DEB_ARCH}.deb"
}

build_appimage() {
  if [[ "$SKIP_APPIMAGE" == "true" ]]; then
    echo "skipping AppImage"
    return
  fi
  # appimagetool's ARCH environment variable uses uname-style names
  # (x86_64/aarch64), while Ostium's package names use amd64/arm64.  Exporting
  # the Debian name makes appimagetool reject the build with "unknown arch".
  local package_arch="$ARCH"
  local appimage_arch="x86_64"
  [[ "$package_arch" == "arm64" ]] && appimage_arch="aarch64"
  local tool="$WORK/appimagetool"
  if ! command -v appimagetool >/dev/null 2>&1; then
    local host_arch
    host_arch="$(uname -m)"
    local tool_arch="x86_64"
    [[ "$host_arch" == "aarch64" || "$host_arch" == "arm64" ]] && tool_arch="aarch64"
    local url="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${tool_arch}.AppImage"
    if ! curl -fsSL --max-time 180 -o "$tool" "$url"; then
      echo "error: appimagetool download failed; AppImage was not built" >&2
      exit 1
    fi
    chmod +x "$tool"
  else
    tool="$(command -v appimagetool)"
  fi
  local appdir="$WORK/AppDir"
  mkdir -p "$appdir/usr/bin" "$appdir/usr/lib/ostium" "$appdir/usr/share/applications" \
    "$appdir/usr/share/icons/hicolor/256x256/apps"
  cp -a "$APP/." "$appdir/usr/lib/ostium/"
  chmod -R u+rwX,go+rX,go-w "$appdir/usr/lib/ostium"
  install -m 0755 "$WORK/sing-box" "$appdir/usr/lib/ostium/sing-box"
  install -d -m 0755 "$appdir/usr/share/doc/ostium"
  [[ -f "$ROOT/LICENSE" ]] && install -m 0644 "$ROOT/LICENSE" "$appdir/usr/share/doc/ostium/LICENSE"
  [[ -f "$ROOT/NOTICE" ]] && install -m 0644 "$ROOT/NOTICE" "$appdir/usr/share/doc/ostium/NOTICE"
  [[ -f "$WORK/SBOM.txt" ]] && install -m 0644 "$WORK/SBOM.txt" "$appdir/usr/share/doc/ostium/core-SBOM.txt"
  cat >"$appdir/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export OSTIUM_ENGINE_PATH="${OSTIUM_ENGINE_PATH:-$HERE/usr/lib/ostium/sing-box}"
exec "$HERE/usr/lib/ostium/ostium" "$@"
EOF
  chmod 0755 "$appdir/AppRun"
  ln -sfn usr/lib/ostium/ostium "$appdir/usr/bin/ostium"
  if [[ -f "$ROOT/web/public/icons/icon-512.png" ]]; then
    install -m 0644 "$ROOT/web/public/icons/icon-512.png" \
      "$appdir/usr/share/icons/hicolor/256x256/apps/ostium.png"
  fi
  cat >"$appdir/ostium.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Ostium
Comment=Personal VPN and proxy console
Exec=ostium
Icon=ostium
Terminal=true
Categories=Network;
EOF
  cp "$appdir/ostium.desktop" "$appdir/usr/share/applications/ostium.desktop"
  export APPIMAGE_EXTRACT_AND_RUN=1
  ARCH="$appimage_arch" "$tool" --no-appstream "$appdir" \
    "$OUT/Ostium-${VERSION}-linux-${package_arch}.AppImage" || {
    echo "error: appimagetool failed; AppImage was not built" >&2
    exit 1
  }
  echo "built $OUT/Ostium-${VERSION}-linux-${package_arch}.AppImage"
}

build_deb
build_appimage
