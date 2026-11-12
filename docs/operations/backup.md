# Backup and restore

## What is included

- SQLite database (online backup API, WAL-safe)
- `master.key` (required to decrypt user passwords and tokens)
- `config.toml`
- certificates and private keys
- a JSON manifest

Core binaries and logs are not included. A backup created with a password is
encrypted with scrypt (N=2^15, r=8, p=1) and AES-256-GCM. Without the password
the file cannot be recovered.

## Create

```bash
sudo -u ostium ostium backup create --password 'a long passphrase'
```

Or **Settings → Maintenance → Backups**. Encrypted files use `.ostb`; plain
archives use `.tar.gz`. Store backups off-host.

## Restore

Preferred: **Settings → Backups → Apply** stages the archive and asks you to
restart both services. The current database is untouched until restart.

CLI with services stopped:

```bash
sudo systemctl stop ostium ostium-core
sudo -u ostium ostium backup restore ./ostium-backup-....ostb --password '...'
sudo systemctl start ostium-core ostium
```

The restore validates the manifest and archive paths, replaces the database and
master key, then runs migrations on the next start. Always test a restore before
relying on backups.

## Retention

Audit logs default to 90 days, jobs 7 days, traffic aggregates 365 days.
Daily automatic local backups are optional and off by default; keep at most
seven copies.
