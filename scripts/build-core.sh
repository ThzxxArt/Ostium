#!/usr/bin/env bash
# Build the pinned sing-box server/data-plane binary from upstream source.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${SINGBOX_VERSION:-1.14.4}"
TAGS="${SINGBOX_TAGS:-with_quic,with_utls,with_clash_api,with_v2ray_api,badlinkname,tfogo_checklinkname0}"
OUT="${ROOT}/dist"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

command -v go >/dev/null || { echo "Go toolchain is required" >&2; exit 1; }
mkdir -p "$OUT"

git clone --depth 1 --branch "v${VERSION}" https://github.com/SagerNet/sing-box.git "$WORK/src"
cd "$WORK/src"
CGO_ENABLED=0 go build -trimpath \
  -ldflags "-s -w -X github.com/sagernet/sing-box/constant.Version=v${VERSION}" \
  -tags "$TAGS" -o "$OUT/sing-box" ./cmd/sing-box
sha256sum "$OUT/sing-box" | awk '{print $1}' > "$OUT/sing-box.sha256"

cat > "$OUT/sing-box.sbom.json" <<EOF
{
  "component": "sing-box",
  "version": "v${VERSION}",
  "source": "https://github.com/SagerNet/sing-box",
  "build_tags": "${TAGS}",
  "platform": "linux-amd64",
  "sha256": "$(cat "$OUT/sing-box.sha256")"
}
EOF

echo "Built $OUT/sing-box (v${VERSION})"
echo "SHA256: $(cat "$OUT/sing-box.sha256")"
