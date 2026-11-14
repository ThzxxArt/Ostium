# syntax=docker/dockerfile:1.7
FROM node:24.19.0-bookworm-slim AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM golang:1.25.5-bookworm AS core
ARG SING_BOX_VERSION=1.14.4
ARG OSTIUM_CORE_VERSION=1.14.4-ostium.1
RUN git clone --depth 1 --branch v${SING_BOX_VERSION} https://github.com/SagerNet/sing-box.git /src
WORKDIR /src
RUN CGO_ENABLED=0 go build -trimpath \
    -tags with_gvisor,with_quic,with_dhcp,with_wireguard,with_utls,with_acme,with_clash_api,with_v2ray_api,with_tailscale,with_ccm,with_ocm,with_cloudflared,with_usbip,with_openvpn,with_openconnect,badlinkname,tfogo_checklinkname0 \
    -ldflags "-X runtime.godebugDefault=multipathtcp=0,tlssha1=1 -checklinkname=0 -X github.com/sagernet/sing-box/constant.Version=${OSTIUM_CORE_VERSION}" \
    -o /out/sing-box ./cmd/sing-box

FROM python:3.13.5-slim-bookworm AS runtime
ARG OSTIUM_VERSION=0.1.1
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OSTIUM_ROLE=server \
    OSTIUM_DATA_DIR=/var/lib/ostium \
    OSTIUM_CONFIG_DIR=/etc/ostium \
    OSTIUM_HOST=0.0.0.0 \
    OSTIUM_ALLOW_INSECURE_BIND=true \
    OSTIUM_PORT=8443 \
    OSTIUM_ENGINE_PATH=/opt/ostium/core/sing-box
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libcap2-bin tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system ostium \
    && useradd --system --gid ostium --home-dir /var/lib/ostium --shell /usr/sbin/nologin ostium

WORKDIR /opt/ostium
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
# The wheel force-includes web/dist, so this must live at the project root
# (the same layout used by CI and release builds).  Copying it into the
# package directory instead silently ships a UI-less wheel.
COPY --from=web /build/web/dist ./web/dist
RUN SETUPTOOLS_SCM_PRETEND_VERSION="${OSTIUM_VERSION#v}" pip install .

COPY --from=core /out/sing-box /opt/ostium/core/sing-box
RUN chmod 0755 /opt/ostium/core/sing-box \
    && setcap cap_net_bind_service=+ep /usr/local/bin/python3.13 \
    && setcap cap_net_bind_service=+ep /opt/ostium/core/sing-box \
    && mkdir -p /var/lib/ostium /etc/ostium \
    && chown -R ostium:ostium /var/lib/ostium /etc/ostium

COPY deploy/docker/entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh

USER ostium
EXPOSE 443/tcp 443/udp 8388/tcp 8388/udp 8443/tcp 80/tcp
VOLUME ["/var/lib/ostium", "/etc/ostium"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD sh -c 'port="${OSTIUM_PORT:-8443}"; curl -fsSk "https://127.0.0.1:$port/healthz" >/dev/null 2>&1 || curl -fsS "http://127.0.0.1:$port/healthz"'
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
