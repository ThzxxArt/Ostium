#!/usr/bin/env bash
# Build the Tailwind stylesheet without Node.js.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${TAILWIND_VERSION:-4.3.5}"
SHA256="${TAILWIND_SHA256:-e47695cee3f0d90623a91f3939b08bdee610eb5ad99340adff9d4145b284d6cc}"
CACHE="${ROOT}/.cache/bin"
BIN="${CACHE}/tailwindcss"

if [ ! -x "$BIN" ]; then
  mkdir -p "$CACHE"
  echo "Downloading Tailwind CSS ${VERSION}"
  curl -fsSL --retry 5 -o "$BIN" \
    "https://github.com/tailwindlabs/tailwindcss/releases/download/v${VERSION}/tailwindcss-linux-x64"
fi
echo "${SHA256}  ${BIN}" | sha256sum -c -
chmod +x "$BIN"

cd "$ROOT"
"$BIN" -i src/ostium/static/src/app.css -o src/ostium/static/css/app.css --minify
echo "Built src/ostium/static/css/app.css ($(wc -c < src/ostium/static/css/app.css) bytes)"
