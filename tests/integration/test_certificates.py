from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select

from ostium.config import Settings
from ostium.db.models import Certificate
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services import certificates as cert_service
from ostium.services.crypto import SecretStore
from ostium.services.users import ensure_inbounds


def test_self_signed_certificate_and_removal(settings: Settings) -> None:
    async def _run() -> None:
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        async with factory() as session:
            await ensure_inbounds(session, store)
            certificate = await cert_service.create_self_signed(
                session, settings, domain="vpn.example.com"
            )
            await session.commit()
            assert Path(certificate.cert_path).is_file()
            assert Path(certificate.key_path).is_file()
            assert certificate.status == "ready"
            await cert_service.use_for_inbounds(session, certificate)
            await session.commit()
            await cert_service.delete_certificate(session, certificate)
            await session.commit()
            remaining = (await session.execute(select(Certificate))).scalars().all()
            assert remaining == []
        await engine.dispose()

    asyncio.run(_run())


def test_manual_certificate_mismatch_rejected(settings: Settings) -> None:
    async def _run() -> None:
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            cert = await cert_service.create_self_signed(session, settings, domain="a.example.com")
            await session.commit()
            cert_pem = Path(cert.cert_path).read_text()
            key_pem = Path(cert.key_path).read_text()
            with pytest.raises(cert_service.CertificateError):
                await cert_service.import_manual(
                    session,
                    settings,
                    domain="b.example.com",
                    cert_pem=cert_pem,
                    key_pem=key_pem,
                )
        await engine.dispose()

    asyncio.run(_run())
