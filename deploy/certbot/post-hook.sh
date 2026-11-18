#!/bin/sh
# After renewal, publish certificates to Caddy's restricted directory and
# restart the reverse proxy. The deploy hook imports them into Ostium.
set -eu

DOMAIN="${OSTIUM_DOMAIN:-}"
if [ -z "$DOMAIN" ] && [ -f /etc/ostium/ostium.env ]; then
  # shellcheck disable=SC1091
  . /etc/ostium/ostium.env
  DOMAIN="${OSTIUM_DOMAIN:-}"
fi
if [ -n "$DOMAIN" ] && [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
  install -d -m 0750 -o root -g caddy "/etc/ostium/tls/$DOMAIN"
  install -m 0640 -o root -g caddy "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" \
    "/etc/ostium/tls/$DOMAIN/fullchain.pem"
  install -m 0640 -o root -g caddy "/etc/letsencrypt/live/$DOMAIN/privkey.pem" \
    "/etc/ostium/tls/$DOMAIN/privkey.pem"
fi
systemctl start caddy 2>/dev/null || true
systemctl reload caddy 2>/dev/null || true
