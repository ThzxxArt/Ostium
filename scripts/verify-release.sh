#!/usr/bin/env bash
# Post-release read-only verification.
#
# Downloads every GitHub Release asset into a temporary directory, verifies
# SHA256SUMS and checks that the expected asset classes exist.  It never
# uploads, edits or replaces anything.
set -euo pipefail

VERSION=""
REPO="${OSTIUM_REPO:-ThzxxArt/Ostium}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    -h|--help) echo "usage: $0 --version 0.1.1 [--repo owner/name]"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [[ -z "$VERSION" ]]; then
  echo "--version is required" >&2
  exit 2
fi
if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required" >&2
  exit 2
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
gh release download "v$VERSION" --repo "$REPO" --dir "$WORK"
cd "$WORK"
if [[ ! -f SHA256SUMS ]]; then
  echo "SHA256SUMS is missing" >&2
  exit 1
fi
sha256sum -c SHA256SUMS

require_glob() {
  local pattern="$1" label="$2"
  # shellcheck disable=SC2086
  if ! compgen -G "$pattern" >/dev/null; then
    echo "missing $label asset: $pattern" >&2
    return 1
  fi
  return 0
}

require_glob "*.whl" "wheel" || exit 1
require_glob "*.tar.gz" "sdist/core archive" || exit 1
require_glob "*-setup.exe" "Windows setup" || exit 1
require_glob "*.dmg" "macOS DMG" || exit 1
require_glob "*.deb" "Linux DEB" || exit 1
require_glob "*.AppImage" "Linux AppImage" || exit 1
require_glob "core-manifest.json" "core manifest" || exit 1
require_glob "ostium-sbom.cdx.json" "SBOM" || exit 1
require_glob "install-online.sh" "online installer" || exit 1
require_glob "install-online.ps1" "PowerShell installer" || exit 1

echo "release v$VERSION assets verified in read-only mode ($(find . -maxdepth 1 -type f | wc -l) files)"
