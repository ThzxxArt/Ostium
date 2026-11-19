# Ostium Server 0.2.5 — Release Notes

Ostium 0.2.5 is a UI/Admin correctness release.

## Fixed

- **Settings page:** fields now render as real inputs instead of
  `<django.forms.fields.CharField object ...>`; labels/help are Chinese; the
  save bar no longer covers fields.
- **Certificate import:** moved to the Aurora console at
  `/certificates/import/`, with the same layout as other pages and Chinese
  labels. The old admin URL redirects there.
- **System page:** configuration status is now explained in plain language;
  the two “9” values are internal revision counters, shown as
  `配置应用状态 / 已同步 / 内部修订号`, not software versions.
- **API docs:** Swagger UI uses the local `drf-spectacular-sidecar` assets with a
  CSP nonce, so `/api/docs` is no longer blank.
- **Django Admin:** app groups are labelled in Chinese.
- **User detail:** quota shows `100.0 GiB` instead of raw bytes; quota cycle and
  validation messages are Chinese.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- --domain vpn.example.com --with-caddy
```

```bash
pip install ostium-ctl==0.2.5
docker pull ghcr.io/thzxxart/ostium-server:0.2.5
```

## Upgrade

0.2.0–0.2.4 can upgrade in place:

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --version 0.2.5
```

## Published channels

- PyPI: https://pypi.org/project/ostium-ctl/0.2.5/
- GHCR: `ghcr.io/thzxxart/ostium-server:0.2.5` and `:latest`
- GitHub Release: `v0.2.5`

## Verification

- Full UI screenshot suite covers every console page plus admin index,
  changelists, certificate import and API docs.
- Settings field rendering, certificate import POST, system revision text and
  Swagger CSP are covered by automated tests.
- CI/UI run on the release commit.
