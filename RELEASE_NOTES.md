# Ostium Server 0.2.8 — Release Notes

Ostium 0.2.8 fixes subscription links being clipped and makes copying them
reliable.

## Fixed

- Full subscription URLs and single-node URIs now wrap at any character instead
  of being truncated with an ellipsis. The complete link is visible and
  selectable with one click.
- Every full URL has an inline **复制** button.
- Clipboard writes now fall back to the legacy copy path when the async
  Clipboard API is denied, instead of failing silently.
- Grid and flex children can shrink below their content width, so long links no
  longer push subscription panels past the viewport.

## Verification

- Desktop and mobile UI tests assert full-link fields have no horizontal or
  vertical clipping.
- The copy button is clicked and the clipboard content is compared with the
  complete URL.
- 378 tests passed / 2 skipped; 8 UI tests passed.
- Screenshots: `audit-subscription-links-1440.png`,
  `audit-subscription-links-390.png`.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

```bash
pip install ostium-ctl==0.2.8
docker pull ghcr.io/thzxxart/ostium-server:0.2.8
```

## Upgrade

0.2.0–0.2.7 can upgrade in place:

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --version 0.2.8
```

## Published channels

- PyPI: https://pypi.org/project/ostium-ctl/0.2.8/
- GHCR: `ghcr.io/thzxxart/ostium-server:0.2.8` and `:latest`
- GitHub Release: `v0.2.8`
