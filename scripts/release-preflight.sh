#!/usr/bin/env bash
# Validate that every live version source and release artifact agrees.
#
# Usage: scripts/release-preflight.sh [--version X.Y.Z] [--tag vX.Y.Z]
# Exit codes: 0 = ready to tag, 1 = inconsistency, 2 = usage error.
# shellcheck disable=SC2016  # literal installers strings are intentional
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
TAG=""
SKIP_GIT="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --tag) TAG="$2"; shift 2 ;;
    --skip-git) SKIP_GIT="true"; shift ;;
    -h|--help) echo "usage: $0 [--version X.Y.Z] [--tag vX.Y.Z] [--skip-git]"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]]; then
  echo "invalid version: $VERSION" >&2
  exit 2
fi
if [[ -n "$TAG" ]]; then
  if [[ "$TAG" != "v$VERSION" ]]; then
    echo "tag $TAG does not match VERSION $VERSION" >&2
    exit 1
  fi
fi

fail=0
check_contains() {
  local file="$1" needle="$2"
  if ! grep -Fq -- "$needle" "$ROOT/$file"; then
    echo "missing '$needle' in $file" >&2
    fail=1
  fi
}
check_not_contains() {
  local file="$1" needle="$2"
  if grep -Fq -- "$needle" "$ROOT/$file"; then
    echo "stale '$needle' in $file" >&2
    fail=1
  fi
}

check_contains pyproject.toml "fallback_version = \"$VERSION\""
check_contains src/ostium/__init__.py "__version__ = \"$VERSION\""
check_contains web/package.json "\"version\": \"$VERSION\""
check_contains web/package-lock.json "\"version\": \"$VERSION\""
check_contains Dockerfile "ARG OSTIUM_VERSION=$VERSION"
# Compose tracks the mutable `latest` tag so a fresh checkout does not request
# an unpublished version; release jobs still build the immutable VERSION tags.
if ! grep -q "ostium:$VERSION" "$ROOT/deploy/docker/docker-compose.yml" \
  && ! grep -q "ostium:latest" "$ROOT/deploy/docker/docker-compose.yml"; then
  echo "missing versioned or latest ostium image in deploy/docker/docker-compose.yml" >&2
  exit 1
fi
check_contains scripts/build-windows.ps1 "[string]\$Version = \"$VERSION\""
check_contains scripts/build-sbom.py "app_version = \"$VERSION\""
check_contains scripts/build-core-manifest.py "\"$VERSION\""
check_contains README.md "$VERSION"
check_contains CHANGELOG.md "## [$VERSION]"
check_contains RELEASE_NOTES.md "$VERSION"
check_contains docs/release-status.md "$VERSION"

# Installers must follow the newest release instead of pinning an old one.
check_contains scripts/install-online.sh 'VERSION="${OSTIUM_VERSION:-latest}"'
check_contains scripts/install-online.ps1 '[string]$Version = "latest"'

# These files must never carry a hardcoded older release again.
for file in \
  scripts/install-online.sh \
  scripts/install-online.ps1 \
  scripts/build-linux-packages.sh \
  scripts/build-macos.sh \
  scripts/build-windows.ps1 \
  scripts/build-sbom.py \
  scripts/build-core-manifest.py \
  Dockerfile \
  deploy/docker/docker-compose.yml \
  web/package.json \
  pyproject.toml \
  src/ostium/__init__.py; do
  if grep -Eq '(^|[^0-9])0\.1\.[01]([^0-9]|$)' "$ROOT/$file"; then
    echo "stale 0.1.0/0.1.1 version in $file" >&2
    fail=1
  fi
done

if [[ "$SKIP_GIT" != "true" && -d "$ROOT/.git" ]]; then
  dirty="$(git -C "$ROOT" status --porcelain)"
  if [[ -n "$dirty" ]]; then
    echo "working tree is not clean; commit release metadata before tagging" >&2
    fail=1
  fi
fi

if [[ "$fail" -ne 0 ]]; then
  echo "release preflight failed for $VERSION" >&2
  exit 1
fi
echo "release preflight passed for $VERSION"
