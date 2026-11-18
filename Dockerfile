# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.14
ARG SINGBOX_VERSION=v1.14.4
ARG TAILWIND_VERSION=v4.3.5

FROM golang:1.27-bookworm AS core
ARG SINGBOX_VERSION
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${SINGBOX_VERSION}" https://github.com/SagerNet/sing-box.git /src
WORKDIR /src
RUN CGO_ENABLED=0 go build \
    -tags "with_quic,with_utls,with_clash_api,with_v2ray_api,badlinkname,tfogo_checklinkname0" \
    -trimpath -ldflags "-s -w" \
    -o /out/sing-box ./cmd/sing-box

FROM debian:bookworm-slim AS css
ARG TAILWIND_VERSION
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL --retry 5 -o /usr/local/bin/tailwindcss \
    "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-x64" \
    && chmod +x /usr/local/bin/tailwindcss
WORKDIR /build
COPY src/ostium/static/src/app.css ./app.css
COPY src/ostium/templates ./templates
COPY src/ostium/templatetags ./templatetags
RUN tailwindcss -i app.css -o app.css.min --minify

FROM python:${PYTHON_VERSION}-slim AS runtime
ARG SINGBOX_VERSION
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=ostium.config.settings.prod \
    OSTIUM_DATA_DIR=/var/lib/ostium \
    OSTIUM_SINGBOX_PATH=/opt/ostium/core/sing-box
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tzdata && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md VERSION LICENSE NOTICE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-install-project \
    && uv sync --frozen --no-dev
COPY --from=css /build/app.css.min /app/src/ostium/static/css/app.css
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
