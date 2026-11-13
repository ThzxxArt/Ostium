from __future__ import annotations

import pytest

from ostium.config import Settings
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.public_url import (
    normalize_base_url,
    public_base_url,
    public_base_url_or_default,
)
from ostium.services.settings import set_setting


def test_normalize_base_url() -> None:
    assert normalize_base_url("https://vpn.example.com/") == "https://vpn.example.com"
    assert normalize_base_url("http://127.0.0.1:8443") == "http://127.0.0.1:8443"
    for value in (
        "ftp://example.com",
        "https://",
        "https://user:pass@example.com",
        "https://example.com/path?x=1",
        "https://example.com/#fragment",
    ):
        with pytest.raises(ValueError):
            normalize_base_url(value)


async def test_public_base_url_precedence(settings: Settings) -> None:
    engine = create_engine(settings.paths.db_path)
    await create_schema(engine)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            assert await public_base_url(session, settings) == f"http://127.0.0.1:{settings.port}"

            await set_setting(session, "server", {"domain": "vpn.example.com"})
            await session.commit()
            assert await public_base_url(session, settings) == "https://vpn.example.com"

            await set_setting(session, "public_base_url", "https://edge.example.com")
            await session.commit()
            assert await public_base_url(session, settings) == "https://edge.example.com"

            await set_setting(session, "public_base_url", "not-a-url")
            await session.commit()
            assert await public_base_url(session, settings) == "https://vpn.example.com"

            await set_setting(session, "server", {"domain": "https://full.example.com/"})
            await session.commit()
            assert await public_base_url(session, settings) == "https://full.example.com"
            assert await public_base_url_or_default(session, settings) == "https://full.example.com"
    finally:
        await engine.dispose()


async def test_public_base_url_default_on_failure(settings: Settings, monkeypatch) -> None:
    import ostium.services.public_url as module

    async def fail(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(module, "public_base_url", fail)
    assert await module.public_base_url_or_default(None, settings) == (
        f"http://127.0.0.1:{settings.port}"
    )
