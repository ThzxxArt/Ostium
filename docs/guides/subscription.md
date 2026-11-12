# Subscriptions

Every enabled user can have one subscription token. The token is a secret:
anyone with the URL can use the user's credentials.

## Formats

| Format | URL | Use |
|---|---|---|
| Ostium Profile v1 | `/sub/<token>?format=ostium` | Ostium client; full metadata |
| Base64 URI list | `/sub/<token>?format=base64` | v2rayN and compatible clients |
| Clash Meta YAML | `/sub/<token>?format=clash` | Clash Meta / Mihomo |
| sing-box JSON | `/sub/<token>?format=singbox` | sing-box outbounds |

The response uses `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and
rate limits 60 requests/minute/IP. Disabled, expired or over-quota users receive
403; unknown tokens receive 404.

## Importing

In Ostium: **Profiles → Import**, paste the URL, a share link, JSON, or scan a
QR image. Subscription-backed profiles refresh once per day and keep the last
successful copy if a refresh fails.

Third-party clients: export the Base64 or Clash format. The URLs contain the
standard VLESS/Hysteria2/Trojan/SS2022 parameters.

## Rotating

Rotate the subscription token in **Subscriptions** or the user drawer. The old
URL stops working immediately. Rotating credentials (UUID/passwords) is a
separate action and disconnects active sessions.

## Security

- Never post a subscription URL in a public issue or screenshot.
- Prefer HTTPS for the subscription endpoint when using a public domain.
- Tokens are stored as a SHA-256 hash plus an encrypted copy; they are not
  written to logs.
