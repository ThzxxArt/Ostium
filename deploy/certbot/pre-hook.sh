#!/bin/sh
# certbot standalone renewal cannot bind :80 while Caddy owns it.
set -eu
systemctl stop caddy 2>/dev/null || true
