#!/usr/bin/env bash
# Build the Ostium sing-box core from the pinned upstream tag.
#
# Requirements: Go 1.25.5, git, tar, sha256sum.
# Usage: ./scripts/build-core.sh [--all|--os linux|darwin|windows] [--arch amd64|arm64]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="1.14.4"
OSTIUM_VERSION="1.14.4-ostium.1"
GO_VERSION="1.25.5"
SRC_DIR="${OSTIUM_CORE_SRC:-$ROOT/.build/sing-box}"
OUT_DIR="${OSTIUM_CORE_OUT:-$ROOT/dist/core}"
TAGS="with_gvisor,with_quic,with_dhcp,with_wireguard,with_utls,with_acme,with_clash_api,with_v2ray_api,with_tailscale,with_ccm,with_ocm,with_cloudflared,with_usbip,with_openvpn,with_openconnect,badlinkname,tfogo_checklinkname0"
WINDOWS_TAGS="$TAGS,with_purego"
LDFLAGS="-X runtime.godebugDefault=multipathtcp=0,tlssha1=1 -checklinkname=0"

targets=(
  "linux amd64"
  "linux arm64"
  "darwin amd64"
  "darwin arm64"
  "windows amd64"
)

if [[ "${1:-}" == "--os" ]]; then
  targets=("$2 ${3:-amd64}")
fi

command -v go >/dev/null || { echo "Go $GO_VERSION is required" >&2; exit 1; }
actual_go="$(go version | awk '{print $3}' | sed 's/^go//')"
if [[ "$actual_go" != "$GO_VERSION" ]]; then
  echo "warning: expected Go $GO_VERSION, found $actual_go" >&2
fi

mkdir -p "$OUT_DIR"
if [[ ! -d "$SRC_DIR/.git" ]]; then
  git clone --depth 1 --branch "v$VERSION" https://github.com/SagerNet/sing-box.git "$SRC_DIR"
else
  git -C "$SRC_DIR" fetch --depth 1 origin "refs/tags/v$VERSION:refs/tags/v$VERSION"
  git -C "$SRC_DIR" checkout -f "v$VERSION"
fi

for target in "${targets[@]}"; do
  read -r os arch <<<"$target"
  name="ostium-core-${OSTIUM_VERSION}-${os}-${arch}"
  dir="$OUT_DIR/$name"
  binary="sing-box"
  [[ "$os" == "windows" ]] && binary="sing-box.exe"
  mkdir -p "$dir"
  tags="$TAGS"
  [[ "$os" == "windows" ]] && tags="$WINDOWS_TAGS"
  echo "==> building $name"
  (
    cd "$SRC_DIR"
    CGO_ENABLED=0 GOOS="$os" GOARCH="$arch" go build -trimpath \
      -tags "$tags" \
      -ldflags "$LDFLAGS -X github.com/sagernet/sing-box/constant.Version=$OSTIUM_VERSION" \
      -o "$dir/$binary" ./cmd/sing-box
  )
  cp "$SRC_DIR/LICENSE" "$dir/LICENSE"
  {
    echo "sing-box $OSTIUM_VERSION"
    echo "upstream tag: v$VERSION"
    echo "go: $actual_go"
    echo "tags: $tags"
    echo "ldflags: $LDFLAGS"
    echo "source: https://github.com/SagerNet/sing-box/tree/v$VERSION"
    echo "license: GPL-3.0"
    echo "--- go version -m ---"
    go version -m "$dir/$binary"
    echo "--- go list -m all ---"
    (cd "$SRC_DIR" && go list -m all)
  } >"$dir/SBOM.txt"
  tar -C "$dir" -czf "$dir.tar.gz" "$binary" "LICENSE" "SBOM.txt"
  sha256sum "$dir.tar.gz" >"$dir.tar.gz.sha256"
done

echo "Artifacts in $OUT_DIR"
ls -lh "$OUT_DIR"/*.tar.gz
