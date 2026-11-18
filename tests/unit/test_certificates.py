"""Certificate service tests."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from ostium.certificates.models import Certificate
from ostium.certificates.services import (
    delete_certificate,
    generate_self_signed,
    import_certificate,
    parse_certificate,
    refresh_status,
    sync_directory,
)
from ostium.proxy.models import Inbound


@pytest.mark.django_db
def test_self_signed_and_ready(certificate):
    assert certificate.domain == "vpn.example.com"
    assert certificate.status == Certificate.Status.READY
    assert certificate.is_ready
    assert certificate.cert_file.is_file()
    assert certificate.key_file.is_file()
    assert certificate.expires_at > __import__("django.utils.timezone", fromlist=["now"]).now()


def test_parse_rejects_mismatched_key(certificate):
    cert_pem = certificate.cert_file.read_text()
    other = generate_self_signed("other.example.com")
    key_pem = other.key_file.read_text()
    with pytest.raises(ValidationError):
        parse_certificate(cert_pem, key_pem)


@pytest.mark.django_db
def test_self_signed_domain_mismatch(certificate):
    with pytest.raises(ValidationError):
        import_certificate(
            domain="evil.example.com",
            cert_pem=certificate.cert_file.read_text(),
            key_pem=certificate.key_file.read_text(),
        )


@pytest.mark.django_db
def test_refresh_marks_missing_file_invalid(certificate):
    certificate.key_file.unlink()
    refresh_status(certificate)
    certificate.refresh_from_db()
    assert certificate.status == Certificate.Status.INVALID
    assert "missing" in certificate.last_error.lower()


@pytest.mark.django_db
def test_delete_refuses_assigned_certificate(certificate, inbounds):
    inbound = Inbound.objects.get(kind="hysteria2")
    inbound.certificate = certificate
    inbound.save()
    with pytest.raises(ValidationError):
        delete_certificate(certificate)


@pytest.mark.django_db
def test_delete_removes_files(certificate, tmp_path):
    cert_file = certificate.cert_file
    delete_certificate(certificate)
    assert not Certificate.objects.filter(domain="vpn.example.com").exists()
    assert not cert_file.exists()


@pytest.mark.django_db
def test_sync_directory(certificate, tmp_path):
    live = tmp_path / "live" / "vpn.example.com"
    live.mkdir(parents=True)
    (live / "fullchain.pem").write_text(certificate.cert_file.read_text())
    (live / "privkey.pem").write_text(certificate.key_file.read_text())
    Certificate.objects.all().delete()
    imported = sync_directory(tmp_path / "live")
    assert [item.domain for item in imported] == ["vpn.example.com"]
    assert imported[0].auto_renew is True
    assert imported[0].source == Certificate.Source.CERTBOT


@pytest.mark.django_db
def test_sync_empty_directory(tmp_path):
    with pytest.raises(ValidationError):
        sync_directory(tmp_path)
