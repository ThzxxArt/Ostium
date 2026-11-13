from __future__ import annotations

import asyncio
import datetime as dt
import ipaddress
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from sqlalchemy import select

from ostium.config import Settings
from ostium.db.models import Certificate, Inbound
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services import certificates as cert_service
from ostium.services.crypto import SecretStore
from ostium.services.users import ensure_inbounds
from ostium.util.time import utcnow


def _bundle(
    common_name: str,
    *,
    san: list[x509.GeneralName] | None = None,
    expired: bool = False,
    no_san: bool = False,
) -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=10))
        .not_valid_after(now + (dt.timedelta(days=-1) if expired else dt.timedelta(days=30)))
    )
    if not no_san:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(san or [x509.DNSName(common_name)]), critical=False
        )
    certificate = builder.sign(key, hashes.SHA256())
    return (
        certificate.public_bytes(serialization.Encoding.PEM).decode(),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )


def test_self_signed_validation_and_reissue(settings: Settings) -> None:
    async def _run() -> None:
        engine, factory, _store = await _setup(settings)
        async with factory() as session:
            for domain in ("", "a" * 254, "../../etc/passwd", "bad domain"):
                with pytest.raises(cert_service.CertificateError):
                    await cert_service.create_self_signed(session, settings, domain=domain)

            certificate = await cert_service.create_self_signed(
                session, settings, domain="vpn.example.com"
            )
            await session.commit()
            first_path = certificate.cert_path
            assert certificate.issuer == "self-signed"
            assert certificate.source == "self-signed"
            assert certificate.expires_at is not None
            assert cert_service.certificate_pin_sha256(first_path)

            # Reissuing updates the existing row and files in place.
            again = await cert_service.create_self_signed(
                session, settings, domain="vpn.example.com", days=1
            )
            await session.commit()
            assert again.id == certificate.id
            assert again.expires_at == certificate.expires_at
            rows = (await session.execute(select(Certificate))).scalars().all()
            assert len(rows) == 1
        await engine.dispose()

    asyncio.run(_run())


def test_import_manual_variants(settings: Settings) -> None:
    async def _run() -> None:
        engine, factory, _store = await _setup(settings)
        async with factory() as session:
            cert_pem, key_pem = _bundle("*.example.com")
            wildcard = await cert_service.import_manual(
                session,
                settings,
                domain="www.example.com",
                cert_pem=cert_pem,
                key_pem=key_pem,
            )
            await session.commit()
            assert wildcard.domain == "www.example.com"
            assert wildcard.status == "ready"
            with pytest.raises(cert_service.CertificateError):
                await cert_service.import_manual(
                    session,
                    settings,
                    domain="a.b.example.com",
                    cert_pem=cert_pem,
                    key_pem=key_pem,
                )

            ip_cert, ip_key = _bundle(
                "127.0.0.1", san=[x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            )
            ip_row = await cert_service.import_manual(
                session, settings, domain="127.0.0.1", cert_pem=ip_cert, key_pem=ip_key
            )
            await session.commit()
            assert ip_row.domain == "127.0.0.1"

            no_san_cert, no_san_key = _bundle("no-san.example.com", no_san=True)
            with pytest.raises(cert_service.CertificateError, match="does not cover"):
                await cert_service.import_manual(
                    session,
                    settings,
                    domain="no-san.example.com",
                    cert_pem=no_san_cert,
                    key_pem=no_san_key,
                )

            expired_cert, expired_key = _bundle("expired.example.com", expired=True)
            with pytest.raises(cert_service.CertificateError, match="expired"):
                await cert_service.import_manual(
                    session,
                    settings,
                    domain="expired.example.com",
                    cert_pem=expired_cert,
                    key_pem=expired_key,
                )

            _good_cert, good_key = _bundle("other.example.com")
            wrong_cert, _ = _bundle("other.example.com")
            with pytest.raises(cert_service.CertificateError, match="do not match"):
                await cert_service.import_manual(
                    session,
                    settings,
                    domain="other.example.com",
                    cert_pem=wrong_cert,
                    key_pem=good_key,
                )
            with pytest.raises(cert_service.CertificateError, match="not valid PEM"):
                await cert_service.import_manual(
                    session,
                    settings,
                    domain="other.example.com",
                    cert_pem="bad",
                    key_pem="bad",
                )
        await engine.dispose()

    asyncio.run(_run())


def test_inbound_assignment_and_deletion(settings: Settings) -> None:
    async def _run() -> None:
        engine, factory, store = await _setup(settings)
        async with factory() as session:
            await ensure_inbounds(session, store)
            certificate = await cert_service.create_self_signed(
                session, settings, domain="vpn.example.com"
            )
            await session.commit()

            await cert_service.use_for_inbounds(session, certificate, kinds=["hysteria2"])
            await session.commit()
            rows = {row.kind: row for row in (await session.execute(select(Inbound))).scalars()}
            assert rows["hysteria2"].certificate_id == certificate.id
            assert rows["trojan"].certificate_id is None

            await cert_service.use_for_inbounds(session, certificate)
            for kind in ("hysteria2", "trojan"):
                rows[kind].enabled = True
            await session.commit()

            await cert_service.delete_certificate(session, certificate)
            await session.commit()
            assert not Path(certificate.cert_path).exists()
            assert not Path(certificate.key_path).exists()
            rows = {row.kind: row for row in (await session.execute(select(Inbound))).scalars()}
            assert rows["hysteria2"].enabled is False
            assert rows["trojan"].enabled is False
            assert rows["hysteria2"].certificate_id is None
        await engine.dispose()

    asyncio.run(_run())


def test_certificate_pin_and_serialization(settings: Settings) -> None:
    async def _run() -> None:
        engine, factory, _store = await _setup(settings)
        async with factory() as session:
            certificate = await cert_service.create_self_signed(
                session, settings, domain="vpn.example.com"
            )
            await session.commit()
            assert cert_service.certificate_pin_sha256(certificate.cert_path)
            assert cert_service.certificate_pin_sha256("/does/not/exist") is None
            data = cert_service.serialize_certificate(certificate)
            assert data["days_remaining"] is not None
            certificate.expires_at = None
            assert cert_service.serialize_certificate(certificate)["days_remaining"] is None
            rows = await cert_service.list_certificates(session)
            assert len(rows) == 1
        await engine.dispose()

    asyncio.run(_run())


def test_ready_certificate_selection_and_unbound_assignment(settings: Settings) -> None:
    async def _run() -> None:
        engine, factory, store = await _setup(settings)
        async with factory() as session:
            await ensure_inbounds(session, store)
            certificate = await cert_service.create_self_signed(
                session, settings, domain="vpn.example.com"
            )
            await session.commit()

            selected = await cert_service.select_ready_certificate(session, certificate.id)
            assert selected is not None
            assert await cert_service.select_ready_certificate(session, None) is None
            assert await cert_service.select_ready_certificate(session, "missing") is None

            path = Path(certificate.cert_path)
            path.unlink()
            assert await cert_service.select_ready_certificate(session, certificate.id) is None
            path.write_text("restored")
            certificate.status = "pending"
            await session.flush()
            assert await cert_service.select_ready_certificate(session, certificate.id) is None
            certificate.status = "ready"
            await session.flush()
            certificate.expires_at = utcnow() - dt.timedelta(days=1)
            await session.flush()
            assert cert_service.certificate_is_ready(certificate) is False
            assert await cert_service.select_ready_certificate(session, certificate.id) is None
            certificate.expires_at = utcnow() + dt.timedelta(days=30)
            await session.flush()

            await cert_service.use_for_unbound(session, certificate, kinds=["hysteria2"])
            await session.commit()
            rows = {row.kind: row for row in (await session.execute(select(Inbound))).scalars()}
            assert rows["hysteria2"].certificate_id == certificate.id
            assert rows["trojan"].certificate_id is None

            with pytest.raises(cert_service.CertificateError, match="not supported"):
                await cert_service.use_for_inbounds(session, certificate, kinds=["vless"])

            certificate.status = "pending"
            await session.flush()
            with pytest.raises(cert_service.CertificateError, match="ready certificate"):
                await cert_service.use_for_inbounds(session, certificate)
            with pytest.raises(cert_service.CertificateError, match="ready certificate"):
                await cert_service.use_for_unbound(session, certificate)
        await engine.dispose()

    asyncio.run(_run())


def test_serialize_expired_certificate(settings: Settings) -> None:
    async def _run() -> None:
        engine, factory, _store = await _setup(settings)
        async with factory() as session:
            certificate = await cert_service.create_self_signed(
                session, settings, domain="vpn.example.com"
            )
            certificate.expires_at = utcnow() - dt.timedelta(days=1)
            await session.flush()
            assert cert_service.serialize_certificate(certificate)["status"] == "expired"
        await engine.dispose()

    asyncio.run(_run())


def test_manual_chain_validation(settings: Settings) -> None:
    async def _run() -> None:
        engine, factory, _store = await _setup(settings)
        async with factory() as session:
            leaf, key = _bundle("vpn.example.com")
            other, _other_key = _bundle("other.example.com")
            with pytest.raises(cert_service.CertificateError, match="out of order"):
                await cert_service.import_manual(
                    session,
                    settings,
                    domain="vpn.example.com",
                    cert_pem=leaf + other,
                    key_pem=key,
                )
        await engine.dispose()

    asyncio.run(_run())


async def _setup(settings: Settings) -> tuple:
    engine = create_engine(settings.paths.db_path)
    await create_schema(engine)
    return engine, create_session_factory(engine), SecretStore.from_data_dir(settings.data_dir)
