from __future__ import annotations

import asyncio
import base64

import pyotp
import pytest

from ostium.config import Settings
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services import auth as auth_service


def test_admin_login_totp_lock_and_session(settings: Settings) -> None:
    async def _run() -> None:
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            admin = await auth_service.create_admin(
                session, username="admin", password="verysecret123"
            )
            await session.commit()
            authenticated = await auth_service.authenticate(
                session,
                settings,
                username="admin",
                password="verysecret123",
                totp_code=None,
                ip="127.0.0.1",
            )
            assert authenticated.id == admin.id
            token, _row = await auth_service.create_session(
                session, admin, ip="127.0.0.1", user_agent="pytest"
            )
            await session.commit()
            resolved = await auth_service.resolve_session(session, token)
            assert resolved is not None

            secret, uri, codes = auth_service.start_totp(admin, settings)
            await session.commit()
            auth_service.confirm_totp(admin, settings, pyotp.TOTP(secret).now())
            assert uri.startswith("otpauth://")
            assert len(codes) == 10
            with pytest.raises(auth_service.AuthError):
                await auth_service.authenticate(
                    session,
                    settings,
                    username="admin",
                    password="verysecret123",
                    totp_code="000000",
                    ip="127.0.0.1",
                )
            await auth_service.disable_totp(session, admin)
            await session.commit()
        await engine.dispose()

    asyncio.run(_run())


def test_local_login_token(settings: Settings) -> None:
    token = auth_service.make_local_login_token(settings)
    assert auth_service.verify_local_login_token(settings, token)
    assert not auth_service.verify_local_login_token(settings, "bogus")


def test_local_login_token_binary_signature_is_not_ambiguous(settings: Settings) -> None:
    """Regression: a signature containing 0x2e must not be split as a delimiter."""

    # 32 random bytes contain a dot about 12% of the time; generate enough
    # tokens that the old rsplit implementation was almost certain to fail.
    tokens = [auth_service.make_local_login_token(settings) for _ in range(400)]
    for token in tokens:
        assert auth_service.verify_local_login_token(settings, token), token
    raw = base64.urlsafe_b64decode(tokens[0] + "=" * (-len(tokens[0]) % 4))
    assert len(raw) == len(raw[:-32]) + 32


def test_local_login_token_rejects_malformed_payloads(settings: Settings) -> None:
    import hashlib
    import hmac
    import time

    from ostium.util.security import load_or_create_master_key

    key = load_or_create_master_key(settings.paths.master_key_path)

    def encode(payload: bytes, signature: bytes | None = None, separator: bool = True) -> str:
        signed = hmac.new(key, payload, hashlib.sha256).digest() if signature is None else signature
        body = payload + (b"." + signed if separator else signed)
        return base64.urlsafe_b64encode(body).decode().rstrip("=")

    now = int(time.time())
    assert not auth_service.verify_local_login_token(settings, encode(b"short"))
    assert not auth_service.verify_local_login_token(settings, encode(b"not-a-number:x"))
    assert not auth_service.verify_local_login_token(settings, encode(b"\xff\xfe:x"))
    assert not auth_service.verify_local_login_token(
        settings, encode(f"{now - 1}:expired".encode())
    )
    # Correctly signed payload with no dot separator must be rejected.
    assert not auth_service.verify_local_login_token(
        settings, encode(f"{now + 30}:no-separator".encode(), separator=False)
    )


def test_password_and_recovery_helpers(settings: Settings) -> None:
    async def _run() -> None:
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            admin = await auth_service.create_admin(
                session, username="admin", password="old-password-123"
            )
            await session.commit()
            assert await auth_service.check_password(admin, "old-password-123")
            await auth_service.set_password(session, admin, "new-password-123")
            await session.commit()
            assert not await auth_service.check_password(admin, "old-password-123")
            api_token, row = await auth_service.create_api_token(
                session, name="ci", scopes=["read"]
            )
            await session.commit()
            assert (await auth_service.resolve_api_token(session, api_token)) is not None
            assert row.scopes == ["read"]
        await engine.dispose()

    asyncio.run(_run())
