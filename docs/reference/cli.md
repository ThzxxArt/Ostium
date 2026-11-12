# CLI reference

All commands support `--json` where meaningful. Exit codes: `0` success, `1`
general, `2` usage, `3` not initialised, `4` service unavailable, `5`
permission, `6` core error.

| Command | Description |
|---|---|
| `ostium init --role server\|client` | Initialise data/config, admin and default inbounds |
| `ostium serve` | Run the control plane / SPA |
| `ostium core-run` | Run the privileged core service (internal) |
| `ostium status [--json]` | Local role, paths, DB, core status |
| `ostium open` | Open the local Web UI |
| `ostium doctor [--json] [--fix]` | Local diagnostics |
| `ostium logs [-f] [--source ostium\|core]` | Tail logs |
| `ostium connect` / `disconnect` | Client connect/disconnect via local API |
| `ostium proxy on\|off\|status` | OS proxy integration |
| `ostium tun on\|off\|status` | TUN toggle via local API |
| `ostium update [--check]` | Update check (installation stays explicit) |
| `ostium diagnostics export` | Redacted diagnostics bundle |
| `ostium user list\|add\|show\|disable\|enable\|rotate\|remove` | Server users |
| `ostium user quota <name> --quota 50G --cycle monthly` | Quota |
| `ostium user subscription <name> [--rotate]` | Print subscription URLs |
| `ostium user export <name> --output profile.json` | Ostium Profile v1 |
| `ostium profile list\|import\|refresh\|remove` | Client profiles |
| `ostium core install --binary PATH \| --url URL --sha256 HASH` | Install core |
| `ostium core status\|version` | Core health/version |
| `ostium backup create\|list\|restore` | Backups |
| `ostium cert list\|issue --self-signed` | Certificates |
| `ostium service install\|uninstall` | systemd units (Linux root) |

Examples:

```bash
ostium user add alice --quota 100G --cycle monthly --expires 2027-01-01T00:00:00+00:00
ostium user subscription alice
ostium profile import https://vpn.example.com/sub/TOKEN?format=ostium --name HK
ostium backup create --password 'long passphrase'
```

Local CLI requests use a loopback token at `<data>/runtime/cli.token`. Remote
automation should create a scoped API token in **Settings → API tokens**.
