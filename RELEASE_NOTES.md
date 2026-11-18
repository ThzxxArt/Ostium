# Ostium Server 0.2.2 — Release Notes

Ostium 0.2.2 fixes the 0.2.1 installer and production static-file pipeline.

## Fixed

- **Release assets are now the default.** The installer downloads the immutable
  GitHub Release wheel, sdist, prebuilt sing-box and `SHA256SUMS`; it verifies
  checksums and installs them. It no longer clones or builds source by default.
- `--from-source` remains available for development and still builds sing-box
  locally with the pinned Go toolchain.
- Removed the Chart.js `sourceMappingURL` comment and moved the Tailwind source
  stylesheet out of `static/`. `collectstatic` with
  `CompressedManifestStaticFilesStorage` now completes.
- Added a regression test that runs `collectstatic` with the real manifest
  storage backend.
- The installer continues to force a managed Python under `/opt/ostium/python`
  that the `ostium` user can execute, and auto-repairs old venvs pointing at
  `/root`.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

Pin the release explicitly if needed:

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --version 0.2.2 --domain vpn.example.com --with-caddy
```

```bash
pip install ostium-ctl==0.2.2
```

```bash
docker pull ghcr.io/thzxxart/ostium-server:0.2.2
```

## Published channels

- PyPI: https://pypi.org/project/ostium-ctl/0.2.2/
- GHCR: `ghcr.io/thzxxart/ostium-server:0.2.2` and `:latest`
- GitHub Release: `v0.2.2`

## Upgrade

0.2.0/0.2.1 can upgrade in place; there are no database schema changes:

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --version 0.2.2
```
