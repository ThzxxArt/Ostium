#!/usr/bin/env bash
# Verify downloaded release artifacts against SHA256SUMS.
set -euo pipefail

DIR="${1:-dist}"
cd "$DIR"
sha256sum -c SHA256SUMS
echo "All artifacts verified."
