"""Certificate validation, storage and certbot synchronisation."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.x509.oid import NameOID
from django.core.exceptions import ValidationError
from django.db import transaction

from ostium import paths
from ostium.operations.services import record_audit

from .models import Certificate

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$|^[a-z0-9-]{1,63}$")


def _sanitize_domain(domain: str) -> str:
    domain = domain.strip().lower().rstrip(".")
    if not _DOMAIN_RE.match(domain):
        raise ValidationError("证书域名无效。")
    return domain


def _public_key_der(key) -> bytes:
    return key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _name_matches(pattern: str, domain: str) -> bool:
    pattern = pattern.lower().rstrip(".")
    domain = domain.lower().rstrip(".")
    if pattern == domain:
        return True
    if pattern.startswith("*.") and domain.count(".") >= pattern.count("."):
        return domain.split(".", 1)[1] == pattern[2:]
    return False


def _cert_names(cert: x509.Certificate) -> list[str]:
    names: list[str] = []
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names.extend(san.get_values_for_type(x509.DNSName))
        names.extend(str(value) for value in san.get_values_for_type(x509.IPAddress))
    except x509.ExtensionNotFound:
        pass
    try:
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        names.extend(attr.value for attr in cn)
    except ValueError, TypeError:
        pass
    return [str(name) for name in names]


def parse_certificate(cert_pem: str, key_pem: str | None = None) -> dict:
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
    except ValueError as exc:
        raise ValidationError("证书不是有效的 PEM。") from exc

    result: dict = {
        "cert": cert,
        "domain": _cert_names(cert)[0] if _cert_names(cert) else "",
        "names": _cert_names(cert),
        "issuer": cert.issuer.rfc4514_string(),
        "subject": cert.subject.rfc4514_string(),
        "expires_at": cert.not_valid_after_utc,
        "fingerprint_sha256": cert.fingerprint(hashes.SHA256()).hex(),
    }

    if key_pem is not None:
        try:
            key = serialization.load_pem_private_key(key_pem.encode("utf-8"), password=None)
        except (ValueError, TypeError) as exc:
            raise ValidationError("私钥不是有效的未加密 PEM。") from exc
        if not isinstance(key, rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey | ed25519.Ed25519PrivateKey):
            raise ValidationError("不支持这种私钥类型。")
        if _public_key_der(cert.public_key()) != _public_key_der(key.public_key()):
            raise ValidationError("证书与私钥不匹配。")
        result["key"] = key

    if result["expires_at"] <= datetime.now(UTC):
        raise ValidationError("证书已过期。")
    return result


def _validate_domain(parsed: dict, domain: str) -> None:
    if not any(_name_matches(name, domain) for name in parsed["names"]):
        raise ValidationError(f"证书不包含域名 {domain}。")


def _write_pair(domain: str, cert_pem: str, key_pem: str) -> tuple[str, str]:
    directory = paths.data_dir() / "certs" / domain
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    cert_file = directory / "fullchain.pem"
    key_file = directory / "privkey.pem"
    cert_file.write_text(cert_pem, encoding="utf-8")
    key_file.write_text(key_pem, encoding="utf-8")
    paths.secure_file(cert_file)
    paths.secure_file(key_file)
    return str(cert_file.relative_to(paths.data_dir())), str(key_file.relative_to(paths.data_dir()))


def _persist(
    *,
    domain: str,
    cert_pem: str,
    key_pem: str,
    parsed: dict,
    source: str,
    auto_renew: bool,
    actor=None,
) -> Certificate:
    domain = _sanitize_domain(domain)
    _validate_domain(parsed, domain)
    cert_path, key_path = _write_pair(domain, cert_pem, key_pem)
    with transaction.atomic():
        certificate, _created = Certificate.objects.update_or_create(
            domain=domain,
            defaults={
                "cert_path": cert_path,
                "key_path": key_path,
                "issuer": parsed["issuer"][:300],
                "subject": parsed["subject"][:300],
                "expires_at": parsed["expires_at"],
                "fingerprint_sha256": parsed["fingerprint_sha256"],
                "status": Certificate.Status.READY,
                "source": source,
                "auto_renew": auto_renew,
                "last_error": "",
            },
        )
    record_audit(
        action="certificate.imported",
        actor=actor,
        target=domain,
        detail={"source": source, "expires_at": parsed["expires_at"].isoformat()},
    )
    return certificate


def import_certificate(
    *,
    domain: str,
    cert_pem: str,
    key_pem: str,
    source: str = Certificate.Source.MANUAL,
    auto_renew: bool = False,
    actor=None,
) -> Certificate:
    parsed = parse_certificate(cert_pem, key_pem)
    return _persist(
        domain=domain,
        cert_pem=cert_pem,
        key_pem=key_pem,
        parsed=parsed,
        source=source,
        auto_renew=auto_renew,
        actor=actor,
    )


def import_from_files(cert_file: Path, key_file: Path, *, auto_renew: bool = False, actor=None) -> Certificate:
    cert_pem = cert_file.read_text(encoding="utf-8")
    key_pem = key_file.read_text(encoding="utf-8")
    parsed = parse_certificate(cert_pem, key_pem)
    domain = parsed["names"][0] if parsed["names"] else cert_file.parent.name
    return _persist(
        domain=domain,
        cert_pem=cert_pem,
        key_pem=key_pem,
        parsed=parsed,
        source=Certificate.Source.CERTBOT if auto_renew else Certificate.Source.MANUAL,
        auto_renew=auto_renew,
        actor=actor,
    )


def sync_directory(directory: Path, *, actor=None) -> list[Certificate]:
    """Import ``live/<domain>/{fullchain,privkey}.pem`` pairs written by certbot."""

    directory = directory.resolve()
    imported: list[Certificate] = []
    if not directory.exists():
        raise ValidationError(f"Directory does not exist: {directory}")

    candidates: set[Path] = set()
    for fullchain in directory.glob("**/fullchain.pem"):
        candidates.add(fullchain.parent)
    for key in directory.glob("**/privkey.pem"):
        candidates.add(key.parent)

    for folder in sorted(candidates):
        cert_file = folder / "fullchain.pem"
        key_file = folder / "privkey.pem"
        if not cert_file.is_file() or not key_file.is_file():
            continue
        certificate = import_from_files(cert_file, key_file, auto_renew=True, actor=actor)
        imported.append(certificate)
    if not imported:
        raise ValidationError("No complete certificate/private-key pairs found.")
    return imported


def generate_self_signed(domain: str, *, days: int = 365, actor=None) -> Certificate:
    domain = _sanitize_domain(domain)
    key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)])
    now = datetime.now(UTC)
    if days < 1:
        raise ValidationError("Certificate lifetime must be at least one day.")
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(domain)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    parsed = parse_certificate(cert_pem, key_pem)
    return _persist(
        domain=domain,
        cert_pem=cert_pem,
        key_pem=key_pem,
        parsed=parsed,
        source=Certificate.Source.SELF_SIGNED,
        auto_renew=False,
        actor=actor,
    )


def delete_certificate(certificate: Certificate, *, actor=None) -> None:
    if certificate.inbounds.exists():
        raise ValidationError("Certificate is assigned to an inbound and cannot be deleted.")
    domain = certificate.domain
    certificate.delete()
    folder = paths.data_dir() / "certs" / domain
    for name in ("fullchain.pem", "privkey.pem"):
        try:
            (folder / name).unlink()
        except OSError:
            pass
    try:
        folder.rmdir()
    except OSError:
        pass
    record_audit(action="certificate.deleted", actor=actor, target=domain)


def refresh_status(certificate: Certificate) -> Certificate:
    status = Certificate.Status.READY
    error = ""
    if certificate.is_expired:
        status = Certificate.Status.EXPIRED
        error = "Certificate has expired."
    elif not certificate.cert_file.is_file() or not certificate.key_file.is_file():
        status = Certificate.Status.INVALID
        error = "Certificate or key file is missing."
    else:
        try:
            parse_certificate(
                certificate.cert_file.read_text(encoding="utf-8"),
                certificate.key_file.read_text(encoding="utf-8"),
            )
        except ValidationError as exc:
            status = Certificate.Status.INVALID
            error = str(exc)
    if (certificate.status, certificate.last_error) != (status, error):
        certificate.status = status
        certificate.last_error = error
        certificate.save(update_fields=["status", "last_error", "updated_at"])
    return certificate


def fingerprint_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certificate_pins(certificate) -> tuple[str, str]:
    """Return (certificate SHA-256 base64, SPKI SHA-256 base64).

    Trojan uses the former as ``pcs``; sing-box uses the latter as
    ``tls.certificate_public_key_sha256``.
    """

    import base64

    cert = x509.load_pem_x509_certificate(certificate.cert_file.read_text(encoding="utf-8").encode("utf-8"))
    der_digest = cert.fingerprint(hashes.SHA256())
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    spki_digest = hashlib.sha256(spki).digest()
    return base64.b64encode(der_digest).decode("ascii"), base64.b64encode(spki_digest).decode("ascii")


__all__ = [
    "certificate_pins",
    "delete_certificate",
    "generate_self_signed",
    "import_certificate",
    "import_from_files",
    "parse_certificate",
    "refresh_status",
    "sync_directory",
]
