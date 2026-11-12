from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from ostium.config import Role, Settings
from ostium.db.models import Inbound
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.crypto import SecretStore
from ostium.services.subscriptions import (
    SubscriptionInactive,
    build_endpoints,
    qr_svg,
    render_subscription,
    subscription_payload,
)
from ostium.services.users import UserError, create_user, ensure_inbounds


def _settings(tmp_path: Path) -> Settings:
    value = Settings(
        role=Role.SERVER,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
        dev=True,
    )
    value.paths.ensure()
    return value


def test_render_all_formats_and_errors(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        async with factory() as session:
            await ensure_inbounds(session, store)
            user, _password, token = await create_user(session, store, name="alice")
            await session.commit()
            inbounds = {row.kind: row for row in (await session.execute(select(Inbound))).scalars()}
            for inbound in inbounds.values():
                inbound.enabled = False
            assert await build_endpoints(session, store, user) == []
            with pytest.raises(SubscriptionInactive):
                await render_subscription(session, store, user, "ostium")
            inbounds["vless"].enabled = True
            user.enabled = False
            with pytest.raises(SubscriptionInactive):
                await render_subscription(session, store, user, "ostium")
            user.enabled = True
            await session.flush()

            ostium, media = await render_subscription(session, store, user, "ostium")
            assert media.startswith("application/json")
            assert json.loads(ostium)["endpoints"]

            text, media = await render_subscription(session, store, user, "base64")
            assert media.startswith("text/plain")
            assert base64.b64decode(text).decode().startswith("vless://")

            clash, media = await render_subscription(session, store, user, "clash")
            assert media.startswith("text/yaml")
            assert "proxies:" in clash

            singbox, media = await render_subscription(session, store, user, "sing-box")
            assert media.startswith("application/json")
            assert json.loads(singbox)["outbounds"]
            assert not any(item["type"] == "selector" for item in json.loads(singbox)["outbounds"])

            # A second endpoint adds the selector outbound.
            inbounds["shadowsocks"].enabled = True
            await session.flush()
            singbox = json.loads((await render_subscription(session, store, user, "singbox"))[0])
            assert any(item["type"] == "selector" for item in singbox["outbounds"])

            with pytest.raises(UserError) as bad:
                await render_subscription(session, store, user, "wireguard")
            assert bad.value.code == "bad_format"

            payload = await subscription_payload(
                session,
                store,
                user,
                base_url="https://ui.example.com/",
                token=token,
            )
            assert len(payload["formats"]) == 4
            assert payload["formats"][0]["url"].startswith("https://ui.example.com/sub/")
            assert payload["qr_svg"].startswith("<?xml") or payload["qr_svg"].startswith("<svg")
            assert payload["user"] == "alice"
        await engine.dispose()

    asyncio.run(_run())


def test_qr_svg() -> None:
    svg = qr_svg("https://example.com/sub/token")
    assert "<svg" in svg
    assert "example.com" in svg or "path" in svg
