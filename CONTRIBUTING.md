# Contributing

## Development

```bash
uv sync
uv run ostium init --role server --dev --no-input --password 'verysecret123'
uv run ostium core-run &
uv run ostium serve --reload
```

Frontend:

```bash
cd web
npm ci
npm run dev        # proxies /api to 127.0.0.1:8443
npm run typecheck
npm run test
npm run build
```

Backend quality gates:

```bash
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src/ostium
uv run pytest
```

Integration tests use a real sing-box binary at `/tmp/opencode/sing-box` or
`OSTIUM_TEST_ENGINE`. The official build covers the proxy protocols; per-user
V2Ray stats require the Ostium custom build from `scripts/build-core.sh`.

## Pull requests

- Keep the locked v0.1.0 scope. Do not silently move features or broaden the
  protocol set.
- Add tests for behavior changes; golden config tests must still pass
  `sing-box check`.
- Do not commit secrets, databases, certificates, core binaries or `web/dist`.
- Security-sensitive changes (core API, auth, encryption, proxy config) need a
  reviewer and a note in `SECURITY.md`/ADR if the threat model changes.
- Run the frontend and backend gates locally; CI is mandatory.

## License

Contributions are licensed under GPL-3.0-or-later. By submitting a PR you agree
that your contribution may be distributed under that license.
