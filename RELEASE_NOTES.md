# Ostium Server 0.2.11 — Release Notes

Ostium 0.2.11 lets you set the automatic-backup password from the console
without storing it in the database or inside backup files.

## Added

- Settings → **自动备份密码** with password + confirmation fields.
- Password is written to `/var/lib/ostium/secrets/backup-password` with mode
  0600. The directory is 0700.
- The page shows whether the active password comes from the environment, the
  page-managed file, or is not configured.
- Page-managed passwords can be cleared from the same panel. Environment
  passwords remain managed by `OSTIUM_BACKUP_PASSWORD`.
- Manual backup form labels and help text are Chinese.

## Changed

- Worker automatic backups, `ostium backup create`, `ostium backup restore`
  and the backup API use the environment variable first, then the page file.
- Dashboard backup onboarding is complete when either password source is set
  and automatic backup is enabled.
- The backup password remains excluded from the database and from `.ostb`
  archives.

## Verification

```text
401 passed, 3 skipped
coverage 90.24%
UI 8 passed
```

Covered: password save/mismatch, file permissions, environment precedence,
worker file fallback, dashboard checklist and clearing the page password.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

```bash
pip install ostium-ctl==0.2.11
docker pull ghcr.io/thzxxart/ostium-server:0.2.11
```

## Upgrade

0.2.0–0.2.10 can upgrade in place:

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --version 0.2.11
```

## Published channels

- PyPI: https://pypi.org/project/ostium-ctl/0.2.11/
- GHCR: `ghcr.io/thzxxart/ostium-server:0.2.11` and `:latest`
- GitHub Release: `v0.2.11`
