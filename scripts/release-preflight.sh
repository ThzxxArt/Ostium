#!/usr/bin/env bash
# Local release gate. Does not publish anything.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> ruff"
uv run ruff check src tests
uv run ruff format --check src tests

echo "==> django check --deploy"
DEPLOY_DATA_DIR="$(mktemp -d)"
DJANGO_SETTINGS_MODULE=ostium.config.settings.prod \
OSTIUM_SECRET_KEY="$(openssl rand -hex 48)" \
OSTIUM_FIELD_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=" \
OSTIUM_ALLOWED_HOSTS="vpn.example.com" \
OSTIUM_PUBLIC_BASE_URL="https://vpn.example.com" \
OSTIUM_REQUIRE_TOTP=true \
OSTIUM_SSL_REDIRECT=true \
OSTIUM_DATA_DIR="$DEPLOY_DATA_DIR" \
uv run python manage.py check --deploy

echo "==> mypy / djlint / bandit / pip-audit"
uv run mypy src
uv run djlint src/ostium/templates --check
uv run bandit -q -r src -ll
uv run pip-audit

echo "==> pytest"
uv run pytest -q --cov=src/ostium --cov-report=term

echo "==> contract"
uv run pytest tests/contract -q

echo "==> UI (requires OSTIUM_UI=1 and Chromium)"
if [ "${OSTIUM_UI:-0}" = "1" ]; then
  DJANGO_ALLOW_ASYNC_UNSAFE=true uv run pytest tests/ui -q
else
  echo "skipped: set OSTIUM_UI=1 to run the browser and axe suite"
fi

echo "==> no Node runtime"
if [ -f package.json ] || [ -f web/package.json ] || grep -R "from 'vue'\|from \"vue\"" -n src 2>/dev/null; then
  echo "Node/Vue remnants found" >&2
  exit 1
fi

echo "==> docs"
uv run mkdocs build --strict

echo "==> build artifacts"
rm -rf dist
uv build
sha256sum dist/* > dist/SHA256SUMS
echo "Release candidate artifacts:"
ls -lh dist
