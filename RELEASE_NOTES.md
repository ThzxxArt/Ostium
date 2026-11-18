# Ostium Server 0.2.4 — Release Notes

Ostium 0.2.4 fixes the production health endpoints and keeps the 0.2.2/0.2.3
installer fixes.

## Fixed

- `SECURE_REDIRECT_EXEMPT` now uses `^healthz$`, `^readyz$` and `^metrics$`.
  Django strips the leading slash before matching, so the previous `^/healthz$`
  patterns never matched and loopback health checks returned 301.
- `ostium web` looks for `gunicorn` next to the running venv Python before
  falling back to `PATH`, fixing systemd startup.
- The installer uses immutable GitHub Release assets by default: wheel, sdist,
  prebuilt sing-box and `SHA256SUMS`, verified before installation. Source
  checkout/build is only used with `--from-source`.
- Production `collectstatic` works with `CompressedManifestStaticFilesStorage`:
  the Chart.js source-map reference is removed and the Tailwind source
  stylesheet lives outside `static/`.
- The installer forces a managed Python under `/opt/ostium/python` that the
  `ostium` user can execute, and auto-repairs old venvs pointing at `/root`.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

```bash
pip install ostium-ctl==0.2.4
docker pull ghcr.io/thzxxart/ostium-server:0.2.4
```

## Upgrade

0.2.0–0.2.3 can upgrade in place; there are no database schema changes:

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --version 0.2.4
```

## Published channels

- PyPI: https://pypi.org/project/ostium-ctl/0.2.4/
- GHCR: `ghcr.io/thzxxart/ostium-server:0.2.4` and `:latest`
- GitHub Release: `v0.2.4`

## Artifacts

- `ostium_ctl-0.2.4-py3-none-any.whl` / `.tar.gz`
- `sing-box` v1.14.4, linux/amd64, with
  `with_quic,with_utls,with_clash_api,with_v2ray_api,badlinkname,tfogo_checklinkname0`
- `sing-box.sha256`, `sing-box.sbom.json`, `SHA256SUMS`
