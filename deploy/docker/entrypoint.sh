#!/bin/sh
set -eu

DATA_DIR="${OSTIUM_DATA_DIR:-/var/lib/ostium}"
if [ ! -f "$DATA_DIR/ostium.db" ]; then
  PASSWORD="${OSTIUM_ADMIN_PASSWORD:-$(python - <<'PY'
import secrets, string
alphabet = string.ascii_letters + string.digits
print(''.join(secrets.choice(alphabet) for _ in range(24)))
PY
)}"
  ostium init --role server --no-input --password "$PASSWORD" ${OSTIUM_DOMAIN:+--domain "$OSTIUM_DOMAIN"}
  echo "=============================================================="
  echo " Ostium initial administrator password: $PASSWORD"
  echo " Open http://<server>:${OSTIUM_PORT:-8443} and sign in."
  echo "=============================================================="
fi

ostium core-run &
CORE_PID=$!
trap 'kill -TERM "$CORE_PID" 2>/dev/null || true; wait "$CORE_PID" 2>/dev/null || true' INT TERM
ostium serve &
UI_PID=$!
trap 'kill -TERM "$UI_PID" "$CORE_PID" 2>/dev/null || true; wait "$UI_PID" "$CORE_PID" 2>/dev/null || true' INT TERM
wait "$UI_PID" "$CORE_PID"
