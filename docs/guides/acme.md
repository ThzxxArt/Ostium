# ACME guide

Ostium includes an ACME HTTP-01 client for Let's Encrypt. It is used for
Hysteria2, Trojan and the public admin UI.

## Requirements

- A domain whose A/AAAA record points at this server.
- TCP port 80 reachable from the internet during issuance.
- The UI service can bind port 80 (it has `CAP_NET_BIND_SERVICE` on the server).

## Issue

1. Open **Certificates → Issue**.
2. Enter the domain and choose **ACME HTTP-01**.
3. Keep the default production directory, or tick **staging** for testing.
4. Watch **Jobs** for progress. The challenge server binds port 80 only for the
   duration of the order and serves a single key authorization.
5. On success the certificate is stored under
   `/var/lib/ostium/certs/<domain>/fullchain.pem` and `privkey.pem` (0600), and
   assigned to Hysteria2/Trojan.

## Renewal

Ostium checks daily and renews certificates with less than 30 days remaining.
A renewal failure creates an alert and leaves the previous certificate in place.
The UI and core are separate, so UI TLS changes require restarting
`ostium.service`; the tunnel keeps running.

## Manual and self-signed

- **Upload** validates PEM parsing, key match, domain coverage and expiry before
  writing files.
- **Self-signed** is intended for Hysteria2 pinning/local testing. Public UI use
  is not recommended (clients must trust or pin it).

## Boundaries

Only HTTP-01 is supported. DNS-01 and TLS-ALPN-01 are intentionally excluded
from v0.1.0 (no DNS provider API, no conflict with the 443 Reality listener).
