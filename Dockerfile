# syntax=docker/dockerfile:1.7
ARG SINGBOX_VERSION=v1.14.4
ARG TAILWIND_VERSION=v4.3.5
ARG TAILWIND_SHA256=e47695cee3f0d90623a91f3939b08bdee610eb5ad99340adff9d4145b284d6cc
ARG VERSION=0.2.8
ARG BUILD_COMMIT=unknown

FROM golang:1.27-bookworm@sha256:4fa7c968ba93f1635670522dbb01a2c78150443e1385746924566079f36570ea AS core
ARG SINGBOX_VERSION
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${SINGBOX_VERSION}" https://github.com/SagerNet/sing-box.git /src
WORKDIR /src
RUN CGO_ENABLED=0 go build \
    -tags "with_quic,with_utls,with_clash_api,with_v2ray_api,badlinkname,tfogo_checklinkname0" \
    -trimpath -ldflags "-s -w -X github.com/sagernet/sing-box/constant.Version=${SINGBOX_VERSION}" \
    -o /out/sing-box ./cmd/sing-box

FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc AS tailwind
ARG TAILWIND_VERSION
ARG TAILWIND_SHA256
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL --retry 5 -o /usr/local/bin/tailwindcss \
    "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-x64" \
    && echo "${TAILWIND_SHA256}  /usr/local/bin/tailwindcss" | sha256sum -c - \
    && chmod +x /usr/local/bin/tailwindcss

FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS runtime
ARG SINGBOX_VERSION
ARG VERSION
ARG BUILD_COMMIT
LABEL org.opencontainers.image.title="Ostium Server" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${BUILD_COMMIT}" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=ostium.config.settings.prod \
    OSTIUM_DATA_DIR=/var/lib/ostium \
    OSTIUM_SINGBOX_PATH=/opt/ostium/core/sing-box
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tzdata && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.14@sha256:1025398289b62de8269e70c45b91ffa37c373f38118d7da036fb8bb8efc85d97 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md VERSION LICENSE NOTICE ./
COPY docs/pypi-readme.md ./docs/pypi-readme.md
COPY src ./src
COPY --from=tailwind /usr/local/bin/tailwindcss /usr/local/bin/tailwindcss
RUN uv sync --frozen --no-dev --no-install-project \
    && uv sync --frozen --no-dev
# Build CSS in the final dependency environment so Tailwind sees both the
# project templates and Unfold's admin templates. Flattening paths in a
# separate stage silently drops the admin utilities.
RUN tailwindcss -i src/ostium/static_src/app.css -o src/ostium/static/css/app.css --minify \
    && test -s src/ostium/static/css/app.css \
    && grep -q '\.table{' src/ostium/static/css/app.css \
    && rm -f /usr/local/bin/tailwindcss
COPY --from=core /out/sing-box /opt/ostium/core/sing-box
RUN useradd --system --uid 10001 --home-dir /var/lib/ostium --create-home ostium \
    && mkdir -p /var/lib/ostium /etc/ostium \
    && chown -R ostium:ostium /var/lib/ostium /app \
    && chmod 0755 /opt/ostium/core/sing-box
USER ostium
EXPOSE 8000 443/tcp 443/udp 8388
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
ENTRYPOINT ["/app/.venv/bin/ostium"]
CMD ["web", "--bind", "0.0.0.0:8000", "--workers", "2"]
