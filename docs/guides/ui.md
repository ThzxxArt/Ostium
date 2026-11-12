# UI guide

Open the console at `http://127.0.0.1:8443` (server, via SSH tunnel) or
`http://127.0.0.1:8787` (client).

## Server pages

- **Overview** — Server Pulse, live rate, today's traffic, online users, alerts,
  certificate health and quick actions.
- **Inbounds** — enable/disable Reality, Hysteria2, Trojan and SS2022; rotate
  Reality keys; see certificate requirements.
- **Users** — create/edit users, quotas, expiry, notes, bulk actions, usage
  charts and subscription access.
- **Subscriptions** — four formats, copy, QR and token rotation.
- **Connections** — live connection table with search and close.
- **Routing** — rule priority, actions, test panel and remote rule sets.
- **Certificates** — ACME/self-signed/upload, expiry ring, renew and assign.
- **Logs / Jobs / Audit** — observe the control plane and long tasks.
- **System** — host metrics, services, doctor and redacted diagnostics.
- **Settings** — theme/language, security, TOTP, API tokens, notifications,
  backups and public UI policy.

## Client pages

- **Home** — large connect orb, profile/endpoint picker, live rates, mode chips.
- **Profiles** — import URL/share link/QR image, refresh, select endpoint.
- **Routing** — smart/global/direct/custom presets and rules.
- **Network** — mixed/system proxy/TUN, ports, MTU/stack and env hints.
- **Statistics** — traffic trend and top destinations.
- **Diagnostics** — port/DNS/route/TUN/proxy/core checks with fix hints.
- **Logs / Settings** — shared with the server.

## Command palette

Press `Cmd/Ctrl+K` and type a page, action or user name. `↑/↓` selects, `Enter`
opens, `Esc` closes. Recent items are remembered locally. Press `?` for the
full shortcut sheet.
