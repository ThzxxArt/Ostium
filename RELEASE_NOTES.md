# Ostium Server 0.2.7 — Release Notes

Ostium 0.2.7 removes every normal-navigation jump from the Aurora console into
Django Admin.

## Fixed

- **新增用户** is now a native console page at `/users/new/` with quota, quota
  cycle, expiry, note and enabled state.
- User editing, certificate management, inbound editing and audit filtering
  all stay inside the Aurora console.
- The console sidebar, user menu and command palette no longer expose Django
  Admin.
- Django Admin is now labelled **Ostium 应急管理** and remains available at
  `/admin/` only as an emergency data-management interface.
- Newly created users persist `expires_at` correctly.
- Remaining visible English eyebrow labels and form headings in the console are
  now Chinese.

## Verification

- 14 console routes assert no `href="/admin/` and no `Django Admin` text.
- User creation asserts quota, quota cycle, expiry, note and enabled state.
- 378 tests passed / 2 skipped; coverage 90.16%.
- Full UI screenshot suite and axe checks pass; 57 screenshots.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

```bash
pip install ostium-ctl==0.2.7
docker pull ghcr.io/thzxxart/ostium-server:0.2.7
```

## Upgrade

0.2.0–0.2.6 can upgrade in place:

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --version 0.2.7
```

## Published channels

- PyPI: https://pypi.org/project/ostium-ctl/0.2.7/
- GHCR: `ghcr.io/thzxxart/ostium-server:0.2.7` and `:latest`
- GitHub Release: `v0.2.7`
