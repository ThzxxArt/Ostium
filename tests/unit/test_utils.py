from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ostium.api.errors import ApiError, problem_response
from ostium.api.ratelimit import LIMITER, SlidingWindowLimiter
from ostium.db.session import (
    create_engine,
    create_schema,
    create_session_factory,
    database_url,
    session_scope,
    tighten_permissions,
)
from ostium.services.settings import all_settings, get_setting, is_initialized, set_setting
from ostium.util.ids import new_id, new_password, new_short_id, new_ss2022_key, new_token, new_uuid
from ostium.util.redact import redact, redact_mapping
from ostium.util.time import as_utc, days_from_now, human_duration, iso, utcnow


def test_time_helpers() -> None:
    naive = datetime(2024, 1, 2, 3, 4, 5)
    aware = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=8)))
    assert as_utc(naive) == datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert as_utc(aware) == datetime(2024, 1, 1, 19, 4, 5, tzinfo=UTC)
    assert iso(None) is None
    assert iso(naive).startswith("2024-01-02T03:04:05")
    assert days_from_now(2) > utcnow()
    assert human_duration(-5) == "0s"
    assert human_duration(5) == "5s"
    assert human_duration(65) == "1m 5s"
    assert human_duration(3665) == "1h 1m"
    assert human_duration(90000) == "1d 1h"


def test_redaction_all_patterns() -> None:
    assert redact("") == ""
    pem = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
    assert redact(pem) == "[REDACTED PRIVATE KEY]"
    assert redact("Authorization: Bearer abc.def-123") == "Authorization: [REDACTED] [REDACTED]"
    assert "password=[REDACTED]" in redact("password=hunter2")
    assert "token: [REDACTED]" in redact('token: "abc"')
    assert redact("ss://abc@example.com:443") == "ss://[REDACTED]"
    assert redact("vless://abc@example.com:443#x") == "vless://[REDACTED]"
    assert redact("trojan://abc@example.com:443") == "vless://[REDACTED]"
    uuid = "2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e"
    assert redact(uuid) == "[REDACTED-UUID]"
    assert redact(uuid, redact_ids=False) == uuid


def test_redact_mapping_nested_and_sensitive() -> None:
    payload = {
        "password": "x",
        "UUID": "2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
        "nested": {"secret": "shh", "safe": "token=abc"},
        "list": ["token=abc"],
        "count": 2,
    }
    result = redact_mapping(payload)
    assert result["password"] == "[REDACTED]"
    assert result["UUID"] == "[REDACTED]"
    assert result["nested"]["secret"] == "[REDACTED]"
    assert "nested" in result["nested"]["safe"] or "token" in result["nested"]["safe"]
    assert result["list"] == ["token=abc"]
    assert result["count"] == 2


def test_identifier_generators() -> None:
    assert new_id() != new_id()
    assert new_uuid().count("-") == 4
    assert len(new_token(16)) >= 20
    assert len(new_password(8)) >= 10
    assert len(new_short_id(4)) == 8
    assert len(new_ss2022_key()) == 24


def test_sliding_window_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]
    monkeypatch.setattr("ostium.api.ratelimit.time.monotonic", lambda: now[0])
    limiter = SlidingWindowLimiter()
    assert limiter.allow("k", 2, 10) is True
    assert limiter.allow("k", 2, 10) is True
    assert limiter.allow("k", 2, 10) is False
    now[0] = 111.0
    assert limiter.allow("k", 2, 10) is True
    limiter.reset("k")
    assert limiter.allow("k", 1, 10) is True
    limiter.reset()
    assert limiter.allow("k", 1, 10) is True
    assert LIMITER.allow("other", 1, 1) is True
    LIMITER.reset()


def test_problem_response_extra_and_headers() -> None:
    class Request:
        class State:
            request_id = "rid"

        state = State()

    error = ApiError(
        429, "slow down", "rate_limited", headers={"Retry-After": "10"}, extra={"x": 1}
    )
    response = problem_response(Request(), error)  # type: ignore[arg-type]
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "10"
    assert b'"x":1' in response.body
    assert b'"request_id":"rid"' in response.body


def test_database_helpers_and_session_scope(tmp_path: Path) -> None:
    async def _run() -> None:
        path = tmp_path / "db.sqlite"
        assert database_url(path) == f"sqlite+aiosqlite:///{path}"
        engine = create_engine(path)
        await create_schema(engine)
        await create_schema(engine)  # idempotent bootstrap
        factory = create_session_factory(engine)
        async with session_scope(factory) as session:
            await set_setting(session, "a", 1)
        async with factory() as session:
            assert await get_setting(session, "a") == 1
            assert await get_setting(session, "missing", "fallback") == "fallback"
            await set_setting(session, "a", 2)
            await set_setting(session, "b", {"nested": True})
            await session.commit()
            assert await all_settings(session) == {"a": 2, "b": {"nested": True}}
            assert await is_initialized(session) is False
            await set_setting(session, "initialized", True)
            assert await is_initialized(session) is True

        with pytest.raises(RuntimeError):
            async with session_scope(factory):
                raise RuntimeError("boom")

        await engine.dispose()

    import asyncio

    asyncio.run(_run())


def test_tighten_permissions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if Path("/").stat().st_mode is None:  # pragma: no cover
        return
    target = tmp_path / "file"
    target.write_text("x")
    tighten_permissions(target)
    if Path("/").stat().st_mode is not None:
        assert target.exists()
    missing = tmp_path / "missing"
    tighten_permissions(missing)
    assert not missing.exists()

    import ostium.db.session as session_module

    monkeypatch.setattr(session_module.os, "name", "nt")
    tighten_permissions(target)
    assert target.exists()
