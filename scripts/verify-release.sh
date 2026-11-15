#!/usr/bin/env bash
# Post-release read-only verification.
#
# Downloads every GitHub Release asset into a temporary directory, verifies
# SHA256SUMS and checks that the expected asset classes exist.  It never
# uploads, edits or replaces anything.
set -euo pipefail

VERSION=""
REPO="${OSTIUM_REPO:-ThzxxArt/Ostium}"
SKIP_ATTESTATION="false"
SKIP_PYPI="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --skip-attestation) SKIP_ATTESTATION="true"; shift ;;
    --skip-pypi) SKIP_PYPI="true"; shift ;;
    -h|--help)
      echo "usage: $0 --version 0.1.4 [--repo owner/name] [--skip-attestation] [--skip-pypi]"
      exit 0
      ;;
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

# The version in filenames must match the requested release, not whatever
# happened to be left in a build directory.
python3 - "$VERSION" <<'PY'
import json
import pathlib
import sys

version = sys.argv[1]
names = [path.name for path in pathlib.Path(".").iterdir() if path.is_file()]
wheels = [name for name in names if name.endswith(".whl")]
sdists = [name for name in names if name.endswith(".tar.gz")]
if not any(f"ostium_ctl-{version}-" in name for name in wheels):
    raise SystemExit(f"no wheel for {version}")
if not any(f"ostium_ctl-{version}.tar.gz" == name for name in sdists):
    raise SystemExit(f"no sdist for {version}")

manifest = json.loads(pathlib.Path("core-manifest.json").read_text())
required = {
    ("linux", "amd64"),
    ("linux", "arm64"),
    ("darwin", "amd64"),
    ("darwin", "arm64"),
    ("windows", "amd64"),
}
present = {(item["os"], item["arch"]) for item in manifest.get("artifacts", [])}
if not required.issubset(present):
    raise SystemExit(f"core manifest is missing platforms: {sorted(required - present)}")
print(f"filenames and {len(present)} core platforms match {version}")
PY

if [[ "$SKIP_ATTESTATION" != "true" ]]; then
  if ! gh attestation --help >/dev/null 2>&1; then
    echo "gh attestation is unavailable; pass --skip-attestation only for a draft/dry run" >&2
    exit 1
  fi
  for asset in *.whl *.tar.gz *.deb *.AppImage *.dmg *-setup.exe SHA256SUMS; do
    [[ -f "$asset" ]] || continue
    gh attestation verify "$asset" --repo "$REPO" >/dev/null
  done
fi

if [[ "$SKIP_PYPI" != "true" ]]; then
  python3 - "$VERSION" <<'PY'
import json
import sys
import urllib.request

version = sys.argv[1]
with urllib.request.urlopen(
    "https://pypi.org/pypi/ostium-ctl/json", timeout=30
) as response:
    payload = json.load(response)
if version not in payload.get("releases", {}):
    raise SystemExit(f"PyPI does not have ostium-ctl=={version}")
print(f"PyPI has ostium-ctl=={version}")
PY
fi

echo "release v$VERSION assets verified in read-only mode ($(find . -maxdepth 1 -type f | wc -l) files)"
