#!/usr/bin/env bash
# Local development helper: starts the control plane and core in one terminal group.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

export OSTIUM_ROLE="${OSTIUM_ROLE:-server}"
export OSTIUM_DATA_DIR="${OSTIUM_DATA_DIR:-$PWD/.dev-data}"
export OSTIUM_DEV=1
export OSTIUM_HOST=127.0.0.1
export OSTIUM_PORT="${OSTIUM_PORT:-8443}"

if [[ ! -f "$OSTIUM_DATA_DIR/ostium.db" ]]; then
  uv run ostium init --role "$OSTIUM_ROLE" --no-input --password "${OSTIUM_ADMIN_PASSWORD:-verysecret123}" || true
fi

uv run ostium core-run &
CORE_PID=$!
trap 'kill $CORE_PID 2>/dev/null || true' EXIT INT TERM
uv run ostium serve --reload
