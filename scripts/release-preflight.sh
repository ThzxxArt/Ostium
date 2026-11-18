#!/usr/bin/env bash
# Local release gate. Does not publish anything.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> ruff"
uv run ruff check src tests
uv run ruff format --check src tests

echo "==> django check --deploy"
DJANGO_SETTINGS_MODULE=ostium.config.settings.prod \
OSTIUM_SECRET_KEY="release-check-secret-key-0123456789" \
OSTIUM_FIELD_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=" \
OSTIUM_ALLOWED_HOSTS="vpn.example.com" \
OSTIUM_PUBLIC_BASE_URL="https://vpn.example.com" \
OSTIUM_REQUIRE_TOTP=true \
OSTIUM_SSL_REDIRECT=true \
OSTIUM_DATA_DIR="$(mktemp -d)" \
uv run python manage.py check --deploy

echo "==> pytest"
uv run pytest -q

echo "==> contract"
uv run pytest tests/contract -q

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
