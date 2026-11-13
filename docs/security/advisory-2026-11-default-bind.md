# Security advisory: default admin UI binding (v0.1.0)

- **Severity**: High
- **Affected versions**: `0.1.0` and earlier
- **Fixed in**: `0.1.1`
- **Component**: server control plane (`ostium serve`), Linux installer, Docker image

## Summary

Ostium `0.1.0` defaulted a server installation to `host = "0.0.0.0"` and served the
admin console over plaintext HTTP on port `8443`. On a cloud host with a permissive
security group this exposed the login page, session APIs and subscription management
to the public internet. The same default was written by `scripts/install.sh`; the
Docker image explicitly required `0.0.0.0` for port publishing.

## Impact

An attacker who could reach `:8443` could:

- attempt password/TOTP authentication against the admin account;
- exploit any pre-authentication vulnerability in the API or SPA;
- observe plaintext traffic between the browser and the server.

Successful authentication would grant full control of proxy users, subscriptions,
certificates and the sing-box core.

## Fixed behaviour in 0.1.1

- `Settings.load()`, `ostium init` and `scripts/install.sh` default to `127.0.0.1`.
- `ostium serve` refuses a non-loopback **plaintext** bind unless
  `allow_insecure_bind = true` (or `--allow-insecure-bind`) is set explicitly.
- Legacy `0.0.0.0` configurations without the opt-in are migrated to `127.0.0.1`
  on first load and written back.
- The Docker image sets `OSTIUM_ALLOW_INSECURE_BIND=true` inside the container, and
  the compose file/documentation require a host firewall or TLS reverse proxy.
- Public UI still requires a ready TLS certificate and confirmed TOTP.

## Mitigation for 0.1.0 installations

1. Edit `/etc/ostium/config.toml` and set `host = "127.0.0.1"`.
2. Restart the service and confirm the listener:
   ```bash
   sudo systemctl restart ostium
   sudo ss -lntp | grep 8443
   ```
3. Do not allow `8443/tcp` from the internet in the cloud security group or host
   firewall.
4. Use an SSH tunnel for remote administration:
   ```bash
   ssh -L 8443:127.0.0.1:8443 user@server
   ```
5. If public administration is required, issue a certificate, enable TOTP, then
   enable Public UI; never expose plaintext HTTP.

## Credits

Found during the internal v0.1.1 security audit.
