from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.responses import Response

from ostium.api import deps, routes_auth
from ostium.api.errors import ApiError


def _request(
    *,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    client_host: str | None = "127.0.0.1",
) -> Request:
    merged = dict(headers or {})
    if cookies:
        merged["cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(key.lower().encode(), value.encode()) for key, value in merged.items()],
        "client": (client_host, 1234) if client_host else None,
    }
    return Request(scope)


def test_client_ip_and_loopback() -> None:
    forwarded = _request(headers={"x-forwarded-for": "203.0.113.5, 10.0.0.1"})
    assert deps.client_ip(forwarded) == "203.0.113.5"
    direct = _request(client_host="198.51.100.7")
    assert deps.client_ip(direct) == "198.51.100.7"
    unknown = _request(client_host=None)
    assert deps.client_ip(unknown) == "unknown"
    assert deps.is_loopback(_request()) is True
    assert deps.is_loopback(_request(client_host="8.8.8.8")) is False


def test_get_services_requires_initialization() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    with pytest.raises(RuntimeError):
        deps.get_services(request)  # type: ignore[arg-type]


def test_get_current_admin_branches(monkeypatch) -> None:
    admin = SimpleNamespace(username="admin")

    async def fake_get_admin(session):  # type: ignore[no-untyped-def]
        return admin

    async def no_admin(session):  # type: ignore[no-untyped-def]
        return None

    async def fake_resolve_token(session, token):  # type: ignore[no-untyped-def]
        return SimpleNamespace(id="token")

    async def no_token(session, token):  # type: ignore[no-untyped-def]
        return None

    async def fake_resolve_session(session, cookie):  # type: ignore[no-untyped-def]
        return None

    async def entrypoint() -> None:
        services = SimpleNamespace(cli_token=lambda: "cli-token")
        session = object()

        monkeypatch.setattr(deps, "get_admin", fake_get_admin)
        monkeypatch.setattr(deps, "resolve_api_token", fake_resolve_token)
        # Bearer API token from a non-loopback client.
        request = _request(headers={"authorization": "Bearer api-token"}, client_host="203.0.113.9")
        assert await deps.get_current_admin(request, services, session) is admin  # type: ignore[arg-type]

        # Valid token but no admin configured.
        monkeypatch.setattr(deps, "get_admin", no_admin)
        with pytest.raises(ApiError) as no_admin_error:
            await deps.get_current_admin(request, services, session)  # type: ignore[arg-type]
        assert no_admin_error.value.status_code == 401

        # Invalid token.
        monkeypatch.setattr(deps, "resolve_api_token", no_token)
        with pytest.raises(ApiError):
            await deps.get_current_admin(request, services, session)  # type: ignore[arg-type]

        # CLI token path, including a token-file OSError.
        def broken_token() -> str:
            raise OSError("unreadable")

        monkeypatch.setattr(deps, "get_admin", fake_get_admin)
        monkeypatch.setattr(deps, "resolve_api_token", no_token)
        broken_services = SimpleNamespace(cli_token=broken_token)
        loopback = _request(headers={"authorization": "Bearer cli-token"})
        with pytest.raises(ApiError):
            await deps.get_current_admin(loopback, broken_services, session)  # type: ignore[arg-type]

        # Cookie session missing/expired.
        monkeypatch.setattr(deps, "resolve_session", fake_resolve_session)
        with pytest.raises(ApiError) as expired:
            await deps.get_current_admin(_request(), services, session)  # type: ignore[arg-type]
        assert expired.value.code == "unauthorized"

        with pytest.raises(ApiError) as expired:
            await deps.get_current_admin(
                _request(cookies={"ostium_session": "x"}),
                services,
                session,  # type: ignore[arg-type]
            )
        assert expired.value.code == "session_expired"

        async def resolved(session, cookie):  # type: ignore[no-untyped-def]
            return admin, SimpleNamespace(id="session")

        monkeypatch.setattr(deps, "resolve_session", resolved)
        assert (
            await deps.get_current_admin(
                _request(cookies={"ostium_session": "x"}),
                services,
                session,  # type: ignore[arg-type]
            )
            is admin
        )
        assert deps.actor_name(admin) == "admin"  # type: ignore[arg-type]

    asyncio.run(entrypoint())


def test_csrf_route_without_token() -> None:
    async def entrypoint() -> None:
        request = SimpleNamespace(cookies={}, state=SimpleNamespace())
        with pytest.raises(ApiError) as error:
            await routes_auth.csrf(request, Response())  # type: ignore[arg-type]
        assert error.value.status_code == 500

    asyncio.run(entrypoint())
