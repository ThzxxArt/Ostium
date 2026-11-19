# Ostium Server 0.2.6 — Release Notes

Ostium 0.2.6 fixes the certificate lifecycle and import workflow.

## Fixed

- Existing certbot certificates are imported automatically during install and
  upgrade; the console also has a **同步 certbot** action for staged certs.
- The inbound TLS selector lists synced certificates immediately and links to
  certificate management/import.
- Certificate import now supports:
  - uploading certificate and private-key files;
  - selecting a staged server certificate directory under
    `/var/lib/ostium/imports`;
  - pasting PEM as an advanced option.
- The domain field is optional and is auto-detected from the certificate SAN.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

```bash
pip install ostium-ctl==0.2.6
docker pull ghcr.io/thzxxart/ostium-server:0.2.6
```

## Upgrade

0.2.0–0.2.5 can upgrade in place:

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --version 0.2.6
```

## Published channels

- PyPI: https://pypi.org/project/ostium-ctl/0.2.6/
- GHCR: `ghcr.io/thzxxart/ostium-server:0.2.6` and `:latest`
- GitHub Release: `v0.2.6`

## Verification

- Certificate upload, staged-path import, paste import and console import view
  are covered by automated tests.
- Full UI screenshot suite and axe checks remain in place.
- CI/UI run on the release commit.
