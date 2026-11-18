# Contributing

## Ground rules

- Server-only: no client, TUN, SPA or Node toolchain.
- No 0.1.x compatibility, migration or deprecated shims.
- Do not add a custom core API; the worker supervises sing-box.
- Every configuration change must pass the real `sing-box check`.
- UI changes must keep WCAG 2.2 AA and the responsive breakpoints.

## Setup

```bash
uv sync --extra dev
uv run ostium migrate
uv run ostium init --username admin --password 'Change-This-Password-2026'
uv run ostium web
```

Build the data-plane binary with the required tags:

```bash
bash scripts/build-core.sh
cp dist/sing-box .cache/bin/sing-box
```

## Checks

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest
uv run pytest tests/contract
uv run mkdocs build --strict
uv run python manage.py check --deploy
```

## Pull requests

- Keep changes focused and explain the security impact.
- Add tests for behavior changes.
- Update docs and `CHANGELOG.md`.
- Do not include secrets, generated databases, certificates or `.env` files.
- UI screenshots are welcome; no Node-based tooling is accepted.

## Commit style

`feat:`, `fix:`, `docs:`, `test:`, `build:`, `ci:`, `refactor:`, `security:`.
