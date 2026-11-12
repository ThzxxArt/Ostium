# Troubleshooting

## The UI does not open

- `ostium status` / `systemctl status ostium`
- Check `http://127.0.0.1:8443/healthz`.
- If `public_ui` is enabled, plain HTTP is expected to fail; use HTTPS and TOTP.
- If you changed the listener, restart `ostium.service`.

## Core is not running

- `ostium core status`
- `journalctl -u ostium-core -n 100`
- `ostium core version`
- The core binary must exist at `<data>/core/sing-box` or `OSTIUM_ENGINE_PATH`.
- A failed `sing-box check` keeps the last-good config; the error is returned to
  the UI and logged.

## A user cannot connect

1. Check the user is enabled, not expired and under quota.
2. Re-download the subscription (rotation invalidates old URLs).
3. Test the endpoint from the client profile page.
4. Verify the server firewall allows 443/tcp and 443/udp.
5. Ensure the client clock is within TOTP/NTP tolerance (Reality does not use
   TOTP, but TLS does care about time).

## Hysteria2 does not start

- It needs a valid certificate; issue or upload one and assign it to the inbound.
- Port 443/udp must be open.
- If the certificate is self-signed, clients must allow insecure/pin; public UI
  certificates cannot be self-signed without warnings.

## TUN fails or leaks

- TUN requires the core service to run as root/SYSTEM (or with CAP_NET_ADMIN).
- Another VPN may own the interface/route table.
- Disable and re-enable TUN; if the core crashed, restart the core to clean
  routes. v0.1.0 does not provide a standalone kill switch.

## ACME fails

- Confirm A/AAAA points here and port 80 is reachable from the public internet.
- Try staging first.
- Check the job error and `journalctl -u ostium`.
- Fall back to manual certificate upload.

## Statistics look wrong after a reload

sing-box counters reset on SIGHUP. Ostium detects the drop, starts a new epoch
and keeps accumulating; up to one 5-second sample may be lost. Quotas are not
billing-grade.

## Recovery

If the UI is unusable, the CLI and database still exist:

```bash
ostium doctor --json
ostium backup create --password '...'
sudo systemctl restart ostium-core
```

If both services are down, restore the last backup and open a local SSH tunnel
to the UI.
