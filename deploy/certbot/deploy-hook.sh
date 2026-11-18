#!/bin/sh
# certbot deploy hook: stage readable certificates, import them into Ostium
# and trigger a configuration apply.
set -eu

if [ -f /etc/ostium/ostium.env ]; then
  # shellcheck disable=SC1091
  . /etc/ostium/ostium.env
fi
DATA_DIR="${OSTIUM_DATA_DIR:-/var/lib/ostium}"
STAGE="$DATA_DIR/imports/letsencrypt"
mkdir -p "$STAGE"

for fullchain in /etc/letsencrypt/live/*/fullchain.pem; do
  [ -f "$fullchain" ] || continue
  key="$(dirname "$fullchain")/privkey.pem"
  [ -f "$key" ] || continue
  domain="$(basename "$(dirname "$fullchain")")"
  install -d -m 0700 -o ostium -g ostium "$STAGE/$domain"
  install -m 0600 -o ostium -g ostium "$fullchain" "$STAGE/$domain/fullchain.pem"
  install -m 0600 -o ostium -g ostium "$key" "$STAGE/$domain/privkey.pem"
done

if [ -x /usr/local/bin/ostium ]; then
  runuser -u ostium -- /usr/local/bin/ostium cert sync --dir "$STAGE"
else
  echo "ostium wrapper not found; certificates were staged but not imported" >&2
  exit 1
fi
