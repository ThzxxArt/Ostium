#!/bin/sh
# certbot deploy hook: import renewed certificates and trigger a config apply.
set -eu

if [ -x /usr/local/bin/ostium ]; then
  runuser -u ostium -- /usr/local/bin/ostium cert sync --dir /etc/letsencrypt/live
else
  echo "ostium wrapper not found; skipping certificate sync" >&2
  exit 1
fi
