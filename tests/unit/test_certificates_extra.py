"""Certificate service edge cases."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from ostium.certificates.models import Certificate
from ostium.certificates.services import (
    _name_matches,
    delete_certificate,
    generate_self_signed,
    import_from_files,
    parse_certificate,
    refresh_status,
    sync_directory,
)


def test_name_matching():
    assert _name_matches("*.example.com", "vpn.example.com")
    assert not _name_matches("*.example.com", "example.com")
    assert _name_matches("vpn.example.com", "VPN.EXAMPLE.COM")


@pytest.mark.django_db
def test_parse_invalid_pem():
    with pytest.raises(ValidationError):
        parse_certificate("not a certificate")


@pytest.mark.django_db
def test_parse_rejects_bad_private_key(certificate):
    with pytest.raises(ValidationError):
        parse_certificate(certificate.cert_file.read_text(), "not a key")


@pytest.mark.django_db
def test_expired_self_signed_rejected():
    with pytest.raises(ValidationError):
        generate_self_signed("expired.example.com", days=-1)


@pytest.mark.django_db
def test_refresh_ready(certificate):
    refresh_status(certificate)
    certificate.refresh_from_db()
    assert certificate.status == Certificate.Status.READY


@pytest.mark.django_db
def test_sync_missing_directory(tmp_path):
    with pytest.raises(ValidationError):
        sync_directory(tmp_path / "missing")


@pytest.mark.django_db
def test_sync_incomplete_pair(tmp_path):
    folder = tmp_path / "live" / "x"
    folder.mkdir(parents=True)
    (folder / "fullchain.pem").write_text("x")
    with pytest.raises(ValidationError):
        sync_directory(tmp_path / "live")


@pytest.mark.django_db
def test_import_from_files(certificate, tmp_path):
    cert_file = tmp_path / "fullchain.pem"
    key_file = tmp_path / "privkey.pem"
    cert_file.write_text(certificate.cert_file.read_text())
    key_file.write_text(certificate.key_file.read_text())
    imported = import_from_files(cert_file, key_file, auto_renew=True)
    assert imported.auto_renew is True


@pytest.mark.django_db
def test_delete_unused(certificate):
    domain = certificate.domain
    delete_certificate(certificate)
    assert not Certificate.objects.filter(domain=domain).exists()


@pytest.mark.django_db
def test_days_remaining_and_tone(certificate):
    assert certificate.days_remaining > 300
    assert certificate.expiry_tone in {"success", "warning", "danger"}
    assert certificate.is_ready is True
