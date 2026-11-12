#!/usr/bin/env bash
# Convenience wrapper for the release installer.
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/install.sh" "$@"
