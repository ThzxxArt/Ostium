# Ostium Server 0.2.3 — Release Notes

Ostium 0.2.3 fixes systemd startup after installing from release assets.

## Fixed

- `ostium web` now looks for `gunicorn` next to the running venv Python before
  falling back to `PATH`. systemd invokes `/opt/ostium/venv/bin/ostium web`
  directly, so `gunicorn` was not discoverable via `shutil.which` even though it
  was installed in `/opt/ostium/venv/bin`.
- The installer uses immutable GitHub Release assets by default: wheel, sdist
  (deployment files), prebuilt sing-box and `SHA256SUMS`, all verified before
  installation. Source checkout/build is only used with `--from-source`.
- Production `collectstatic` works with
  `CompressedManifestStaticFilesStorage`: the Chart.js source-map reference is
  removed and the Tailwind source stylesheet lives outside `static/`.
- The installer forces a managed Python under `/opt/ostium/python` that the
  `ostium` user can execute, and auto-repairs old venvs pointing at `/root`.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

Pin the release:

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --version 0.2.3 --domain vpn.example.com --with-caddy
```

```bash
pip install ostium-ctl==0.2.3
docker pull ghcr.io/thzxxart/ostium-server:0.2.3
```

## Upgrade

0.2.0/0.2.1/0.2.2 can upgrade in place; there are no database schema changes:

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --version 0.2.3
```

## Published channels

- PyPI: https://pypi.org/project/ostium-ctl/0.2.3/
- GHCR: `ghcr.io/thzxxart/ostium-server:0.2.3` and `:latest`
- GitHub Release: `v0.2.3`

## Artifacts

- `ostium_ctl-0.2.3-py3-none-any.whl` / `.tar.gz`
- `sing-box` v1.14.4, linux/amd64, with
  `with_quic,with_utls,with_clash_api,with_v2ray_api,badlinkname,tfogo_checklinkname0`
- `sing-box.sha256`, `sing-box.sbom.json`, `SHA256SUMS`

## Verification

- CI and UI passed on the release commit.
- 367+ tests passed / 1 skipped; coverage above 90%.
- Production `collectstatic` with manifest storage verified from the built wheel.
- Real sing-box v1.14.4 + mihomo contract tests passed.
- PyPI wheel/sdist verified with `scripts/verify-package.py`.
