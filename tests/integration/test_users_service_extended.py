from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from ostium.config import Settings
from ostium.db.models import Inbound
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services import certificates as cert_service
from ostium.services.crypto import SecretStore
from ostium.services.settings import set_setting
from ostium.services.users import (
    UserError,
    create_user,
    decrypt_password,
    decrypt_ss_password,
    decrypt_subscription_token,
    effective_used,
    endpoints_for_user,
    ensure_inbounds,
    get_user_by_name,
    get_user_by_subscription_token,
    inbound_params,
    reset_usage,
    rotate_credentials,
    rotate_subscription,
    serialize_user,
    server_hostname,
    status_of,
)
from ostium.util.security import hash_token
from ostium.util.time import utcnow


async def _setup(settings: Settings) -> tuple:
    engine = create_engine(settings.paths.db_path)
    await create_schema(engine)
    factory = create_session_factory(engine)
    store = SecretStore.from_data_dir(settings.data_dir)
    return engine, factory, store


def test_user_validation_and_credentials(settings: Settings) -> None:
    async def _run() -> None:
        engine, factory, store = await _setup(settings)
        async with factory() as session:
            for name in ("", "   ", "a" * 65, 'bad"', "bad\\", "bad\nname"):
                with pytest.raises(UserError):
                    await create_user(session, store, name=name)
            with pytest.raises(UserError):
                await create_user(session, store, name="alice", quota_cycle="weekly")
            with pytest.raises(UserError):
                await create_user(session, store, name="alice", quota_bytes=-1)

            user, password, token = await create_user(
                session, store, name=" alice ", quota_bytes=100, note="x" * 600
            )
            await session.commit()
            assert user.name == "alice"
            assert len(user.note) == 500
            assert decrypt_password(user, store) == password
            assert decrypt_ss_password(user, store)
            assert decrypt_subscription_token(user, store) == token
            assert user.subscription_token_hash == hash_token(token)

            found = await get_user_by_name(session, "alice")
            assert found is user
            assert await get_user_by_name(session, "nobody") is None
            by_token = await get_user_by_subscription_token(session, store, token)
            assert by_token is user

            user.ss_password_enc = None
            with pytest.raises(UserError, match="no Shadowsocks"):
                decrypt_ss_password(user, store)
            user.subscription_token_enc = None
            assert decrypt_subscription_token(user, store) is None

            user.subscription_token_enc = store.encrypt(
                "different", table="proxy_users", record_id=user.id, field="subscription_token"
            )
            assert await get_user_by_subscription_token(session, store, token) is None
            user.subscription_token_enc = "v1.invalid"
            assert await get_user_by_subscription_token(session, store, token) is None

            user.subscription_token_enc = None
            new_token = await rotate_subscription(session, store, user)
            assert decrypt_subscription_token(user, store) == new_token
            old_uuid = user.uuid
            old_password = decrypt_password(user, store)
            new_password = await rotate_credentials(session, store, user)
            assert new_password != old_password
            assert user.uuid != old_uuid
        await engine.dispose()

    asyncio.run(_run())


def test_status_effective_used_and_serialization(settings: Settings) -> None:
    async def _run() -> None:
        engine, factory, store = await _setup(settings)
        async with factory() as session:
            user, _password, _token = await create_user(session, store, name="alice")
            await session.commit()

            user.enabled = False
            user.disabled_reason = None
            assert status_of(user) == "disabled"
            user.disabled_reason = "quota_exceeded"
            assert status_of(user) == "quota_exceeded"

            user.enabled = True
            user.expires_at = utcnow() - timedelta(seconds=1)
            assert status_of(user) == "expired"

            user.expires_at = utcnow() + timedelta(days=1)
            user.quota_bytes = 10
            user.used_bytes = 10
            assert status_of(user) == "quota_exceeded"
            assert status_of(user, online=True) == "quota_exceeded"

            user.quota_bytes = 0
            user.used_bytes = 0
            assert status_of(user, online=True) == "online"
            assert effective_used(user, -100) == 0
            assert effective_used(user, 5) == 5

            data = serialize_user(user, online=True, reveal={"password": "once"})
            assert data["password"] == "once"
            assert data["online"] is True
            assert data["has_subscription"] is True
        await engine.dispose()

    asyncio.run(_run())


def test_reset_usage_rules(settings: Settings) -> None:
    async def _run() -> None:
        engine, factory, store = await _setup(settings)
        async with factory() as session:
            user, _password, _token = await create_user(session, store, name="alice")
            user.used_bytes = 100
            user.disabled_reason = "quota_exceeded"
            await reset_usage(session, user)
            assert user.used_bytes == 0
            assert user.disabled_reason is None

            user.used_bytes = 100
            user.disabled_reason = "expired"
            user.expires_at = utcnow() + timedelta(days=1)
            await reset_usage(session, user)
            assert user.disabled_reason == "expired"

            user.used_bytes = 100
            user.disabled_reason = "other"
            await reset_usage(session, user)
            assert user.disabled_reason == "other"
        await engine.dispose()

    asyncio.run(_run())


def test_ensure_inbounds_and_params(settings: Settings) -> None:
    async def _run() -> None:
        engine, factory, store = await _setup(settings)
        async with factory() as session:
            first = await ensure_inbounds(session, store)
            await session.commit()
            second = await ensure_inbounds(session, store)
            await session.commit()
            assert {row.kind for row in first} == {"vless", "hysteria2", "trojan", "shadowsocks"}
            assert len(second) == 4
            params = inbound_params(first[0], store)
            assert params

            inbound = first[0]
            inbound.params_enc = None
            assert inbound_params(inbound, store) == {}
            inbound.params_enc = store.encrypt(
                "not-json", table="inbounds", record_id=inbound.id, field="params"
            )
            assert inbound_params(inbound, store) == {}
        await engine.dispose()

    asyncio.run(_run())


def test_ensure_inbounds_partial_existing(settings: Settings) -> None:
    async def _run() -> None:
        engine, factory, store = await _setup(settings)
        async with factory() as session:
            session.add(Inbound(kind="vless", enabled=True, port=443))
            session.add(Inbound(kind="shadowsocks", enabled=True, port=8388))
            await session.commit()
            rows = await ensure_inbounds(session, store)
            await session.commit()
            by_kind = {row.kind: row for row in rows}
            assert set(by_kind) == {"vless", "hysteria2", "trojan", "shadowsocks"}
            assert by_kind["vless"].params_enc is None
            assert by_kind["hysteria2"].params_enc
            assert by_kind["shadowsocks"].params_enc is None
        await engine.dispose()

    asyncio.run(_run())


def test_endpoints_for_user_all_protocols(settings: Settings) -> None:
    async def _run() -> None:
        engine, factory, store = await _setup(settings)
        async with factory() as session:
            await ensure_inbounds(session, store)
            user, _password, _token = await create_user(session, store, name="alice")
            await session.commit()

            cert = await cert_service.create_self_signed(
                session, settings, domain="vpn.example.com"
            )
            await session.commit()
            inbounds = (await session.execute(select(Inbound))).scalars().all()
            for inbound in inbounds:
                inbound.enabled = True
                inbound.certificate_id = cert.id
            await session.commit()

            endpoints = await endpoints_for_user(
                session, store, user, server_host="vpn.example.com", server_name="Display"
            )
            assert {item.protocol.value for item in endpoints} == {
                "vless-reality",
                "hysteria2",
                "trojan",
                "shadowsocks",
            }
            hy2 = next(item for item in endpoints if item.protocol.value == "hysteria2")
            assert hy2.tls.insecure is True
            assert "Display" in hy2.name

            cert.source = "acme"
            await session.flush()
            endpoints = await endpoints_for_user(
                session, store, user, server_host="vpn.example.com"
            )
            hy2 = next(item for item in endpoints if item.protocol.value == "hysteria2")
            assert hy2.tls.insecure is False

            for inbound in inbounds:
                inbound.enabled = False
            await session.flush()
            assert await endpoints_for_user(session, store, user, server_host="x") == []

            # Hysteria2/Trojan without a certificate are skipped.
            for inbound in inbounds:
                if inbound.kind in {"hysteria2", "trojan"}:
                    inbound.enabled = True
                    inbound.certificate_id = None
            await session.flush()
            endpoints = await endpoints_for_user(session, store, user, server_host="x")
            assert not any(item.protocol.value in {"hysteria2", "trojan"} for item in endpoints)
        await engine.dispose()

    asyncio.run(_run())


def test_server_hostname_precedence(settings: Settings) -> None:
    async def _run() -> None:
        engine, factory, _store = await _setup(settings)
        async with factory() as session:
            assert await server_hostname(session) == "127.0.0.1"
            await set_setting(session, "server", {"domain": "domain.example"})
            assert await server_hostname(session) == "domain.example"
            await set_setting(
                session, "server", {"domain": "domain.example", "public_host": "public.example"}
            )
            assert await server_hostname(session) == "public.example"
            await set_setting(session, "server", {"domain": ""})
            assert await server_hostname(session) == "127.0.0.1"
            await set_setting(session, "server", "not-a-dict")
            assert await server_hostname(session) == "127.0.0.1"
        await engine.dispose()

    asyncio.run(_run())
