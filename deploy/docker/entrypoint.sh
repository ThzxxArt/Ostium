#!/bin/sh
set -eu

DATA_DIR="${OSTIUM_DATA_DIR:-/var/lib/ostium}"
if [ ! -f "$DATA_DIR/ostium.db" ]; then
  GENERATED=0
  if [ -n "${OSTIUM_ADMIN_PASSWORD:-}" ]; then
    PASSWORD="$OSTIUM_ADMIN_PASSWORD"
  else
    GENERATED=1
    PASSWORD="$(python - <<'PY'
import secrets, string
alphabet = string.ascii_letters + string.digits
print(''.join(secrets.choice(alphabet) for _ in range(24)))
PY
)"
  fi
  ostium init --role server --no-input --password "$PASSWORD" ${OSTIUM_DOMAIN:+--domain "$OSTIUM_DOMAIN"}
  if [ "$GENERATED" = "1" ]; then
    echo "=============================================================="
    echo " Ostium initial administrator password: $PASSWORD"
    echo " Open http://<server>:${OSTIUM_PORT:-8443} and sign in."
    echo "=============================================================="
  else
    echo "Ostium initialised with the administrator password from OSTIUM_ADMIN_PASSWORD."
  fi
fi

ostium core-run &
CORE_PID=$!
ostium serve &
UI_PID=$!
trap 'kill -TERM "$UI_PID" "$CORE_PID" 2>/dev/null || true' INT TERM

# `wait pid1 pid2` only returns after both children exit.  A crashed core
# would therefore leave a half-dead container running until the UI also died.
# Exit as soon as either child is gone so Docker's restart policy can act.
while kill -0 "$UI_PID" 2>/dev/null && kill -0 "$CORE_PID" 2>/dev/null; do
  sleep 2
done
kill -TERM "$UI_PID" "$CORE_PID" 2>/dev/null || true
wait "$UI_PID" 2>/dev/null || true
wait "$CORE_PID" 2>/dev/null || true
exit 1
