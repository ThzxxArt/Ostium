# Ostium Server 0.2.14 — Release Notes

Ostium 0.2.14 fixes the upgrade pre-flight backup for installations that set
the automatic backup password from the Settings page.

## Fixed

- The installer/upgrade now checks both:
  - `OSTIUM_BACKUP_PASSWORD` in `/etc/ostium/ostium.env`;
  - `/var/lib/ostium/secrets/backup-password` written by Settings.
- A page-managed backup password now triggers the pre-upgrade backup instead
  of only warning and continuing.

## Verification

```text
424 passed, 3 skipped
coverage 90.04%
UI 8 passed
real-client E2E passed
```

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

```bash
pip install ostium-ctl==0.2.14
docker pull ghcr.io/thzxxart/ostium-server:0.2.14
```

## Upgrade

0.2.0–0.2.13 can upgrade in place:

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --version 0.2.14
```

## Published channels

- PyPI: https://pypi.org/project/ostium-ctl/0.2.14/
- GHCR: `ghcr.io/thzxxart/ostium-server:0.2.14` and `:latest`
- GitHub Release: `v0.2.14`
