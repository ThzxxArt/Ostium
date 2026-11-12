"""Certificate storage, self-signed generation and manual import."""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import os
import re
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.config import Settings
from ostium.db.models import Certificate, Inbound
from ostium.util.time import as_utc, iso, utcnow


class CertificateError(Exception):
    def __init__(
        self, message: str, code: str = "certificate_error", status_code: int = 400
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _cert_dir(settings: Settings, domain: str) -> Path:
    safe = domain.replace("/", "_").replace("..", "_")
    return settings.paths.certs_dir / safe


_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def validate_domain(domain: str) -> str:
    """Normalise and validate a certificate domain or IP address.

    Domain input is used as a filesystem directory name, so rejecting path
    separators and control characters here is a security boundary, not just
    user-input polish.
    """

    value = domain.strip().lower().rstrip(".")
    if not value or len(value) > 253:
        raise CertificateError("invalid domain")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    labels = value.split(".")
    if len(labels) < 2 or any(not _LABEL_RE.fullmatch(label) for label in labels):
        raise CertificateError("invalid domain")
    return value


async def create_self_signed(
    session: AsyncSession,
    settings: Settings,
    *,
    domain: str,
    days: int = 3650,
) -> Certificate:
    domain = validate_domain(domain)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, domain),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Ostium Self-Signed"),
        ]
    )
    now = dt.datetime.now(dt.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
    )
    san: list[x509.GeneralName] = []
    try:
        san.append(x509.IPAddress(ipaddress.ip_address(domain)))
    except ValueError:
        san.append(x509.DNSName(domain))
        if not domain.startswith("*."):
            san.append(x509.DNSName(f"*.{domain}"))
    builder = builder.add_extension(x509.SubjectAlternativeName(san), critical=False)
    certificate = builder.sign(key, hashes.SHA256())
    return await _persist(
        session,
        settings,
        domain=domain,
        cert_pem=certificate.public_bytes(serialization.Encoding.PEM).decode(),
        key_pem=key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode(),
        issuer="self-signed",
        source="self-signed",
        expires_at=as_utc(certificate.not_valid_after_utc),
    )


async def import_manual(
    session: AsyncSession,
    settings: Settings,
    *,
    domain: str,
    cert_pem: str,
    key_pem: str,
    source: str = "manual",
) -> Certificate:
    domain = validate_domain(domain)
    try:
        certificate = x509.load_pem_x509_certificate(cert_pem.encode())
        key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    except Exception as exc:
        raise CertificateError("certificate or private key is not valid PEM") from exc
    cert_public = certificate.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    key_public = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if cert_public != key_public:
        raise CertificateError("certificate and private key do not match")
    if not _covers_domain(certificate, domain):
        raise CertificateError(f"certificate does not cover {domain}")
    expires = as_utc(certificate.not_valid_after_utc)
    if expires <= utcnow():
        raise CertificateError("certificate has already expired")
    return await _persist(
        session,
        settings,
        domain=domain,
        cert_pem=cert_pem,
        key_pem=key_pem,
        issuer=certificate.issuer.rfc4514_string(),
        source=source,
        expires_at=expires,
    )


def _covers_domain(certificate: x509.Certificate, domain: str) -> bool:
    try:
        san = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names = san.get_values_for_type(x509.DNSName)
        ips = [str(item) for item in san.get_values_for_type(x509.IPAddress)]
    except x509.ExtensionNotFound:
        return False
    if domain in names or domain in ips:
        return True
    return any(name.startswith("*.") and domain.endswith(name[1:]) for name in names)


async def _persist(
    session: AsyncSession,
    settings: Settings,
    *,
    domain: str,
    cert_pem: str,
    key_pem: str,
    issuer: str,
    source: str,
    expires_at: Any,
) -> Certificate:
    directory = _cert_dir(settings, domain)
    directory.mkdir(parents=True, exist_ok=True)
    cert_path = directory / "fullchain.pem"
    key_path = directory / "privkey.pem"
    cert_path.write_text(cert_pem, encoding="utf-8")
    key_path.write_text(key_pem, encoding="utf-8")
    for path, mode in ((cert_path, 0o644), (key_path, 0o600)):
        if os.name == "posix":
            path.chmod(mode)
    existing = (
        await session.execute(select(Certificate).where(Certificate.domain == domain))
    ).scalar_one_or_none()
    if existing is None:
        existing = Certificate(
            domain=domain,
            cert_path=str(cert_path),
            key_path=str(key_path),
            issuer=issuer,
            expires_at=expires_at,
            status="ready",
            source=source,
        )
        session.add(existing)
    else:
        existing.cert_path = str(cert_path)
        existing.key_path = str(key_path)
        existing.issuer = issuer
        existing.expires_at = expires_at
        existing.status = "ready"
        existing.source = source
        existing.last_error = None
    return existing


async def list_certificates(session: AsyncSession) -> list[Certificate]:
    return list(
        (await session.execute(select(Certificate).order_by(Certificate.domain))).scalars().all()
    )


async def use_for_inbounds(
    session: AsyncSession, certificate: Certificate, *, kinds: list[str] | None = None
) -> None:
    targets = kinds or ["hysteria2", "trojan"]
    inbounds = (
        (await session.execute(select(Inbound).where(Inbound.kind.in_(targets)))).scalars().all()
    )
    for inbound in inbounds:
        inbound.certificate_id = certificate.id
    await session.flush()


async def delete_certificate(session: AsyncSession, certificate: Certificate) -> None:
    inbounds = (
        (await session.execute(select(Inbound).where(Inbound.certificate_id == certificate.id)))
        .scalars()
        .all()
    )
    for inbound in inbounds:
        inbound.enabled = False
        inbound.certificate_id = None
    await session.delete(certificate)
    await session.flush()


def certificate_pin_sha256(cert_path: str) -> str | None:
    try:
        certificate = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
    except Exception:
        return None
    der = certificate.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(der).hexdigest()


def serialize_certificate(certificate: Certificate) -> dict[str, Any]:
    return {
        "id": certificate.id,
        "domain": certificate.domain,
        "issuer": certificate.issuer,
        "expires_at": iso(certificate.expires_at),
        "auto_renew": certificate.auto_renew,
        "status": certificate.status,
        "source": certificate.source,
        "last_error": certificate.last_error,
        "created_at": iso(certificate.created_at),
        "days_remaining": (
            (as_utc(certificate.expires_at) - utcnow()).days if certificate.expires_at else None
        ),
    }
