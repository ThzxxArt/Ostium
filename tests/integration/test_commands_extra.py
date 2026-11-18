"""Management command branches and full restore."""

from __future__ import annotations

import base64
import io

import pytest
from django.core.management import call_command
from django.test import TransactionTestCase

from ostium.certificates.models import Certificate
from ostium.operations.models import Backup
from ostium.proxy.models import ProxyUser


@pytest.mark.django_db
def test_cert_commands(certificate, tmp_path):
    out = io.StringIO()
    call_command("cert", "list", stdout=out)
    assert "vpn.example.com" in out.getvalue()

    cert_file = tmp_path / "fullchain.pem"
    key_file = tmp_path / "privkey.pem"
    cert_file.write_text(certificate.cert_file.read_text())
    key_file.write_text(certificate.key_file.read_text())
    call_command(
        "cert",
        "import",
        "--domain",
        "vpn.example.com",
        "--cert",
        str(cert_file),
        "--key",
        str(key_file),
        stdout=io.StringIO(),
    )
    assert Certificate.objects.filter(domain="vpn.example.com").exists()

    call_command("cert", "self-signed", "--domain", "self.example.com", stdout=io.StringIO())
    assert Certificate.objects.filter(domain="self.example.com").exists()

    live = tmp_path / "live" / "vpn.example.com"
    live.mkdir(parents=True)
    (live / "fullchain.pem").write_text(cert_file.read_text())
    (live / "privkey.pem").write_text(key_file.read_text())
    call_command("cert", "sync", "--dir", str(tmp_path / "live"), stdout=io.StringIO())
    assert Certificate.objects.get(domain="vpn.example.com").auto_renew is True

    call_command("cert", "delete", "self.example.com", stdout=io.StringIO())
    assert not Certificate.objects.filter(domain="self.example.com").exists()


@pytest.mark.django_db
def test_backup_commands(proxy_user):
    out = io.StringIO()
    call_command("backup", "create", "--password", "a-long-backup-password", stdout=out)
    assert Backup.objects.count() == 1
    call_command("backup", "list", stdout=io.StringIO())
    assert Backup.objects.first() is not None
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("backup", "restore", "/nonexistent", "--password", "a-long-backup-password")


@pytest.mark.django_db
def test_doctor_command_reports_failure():
    out = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        call_command("doctor", "--json", stdout=out)
    assert exc.value.code == 1
    assert "checks" in out.getvalue()


@pytest.mark.django_db
def test_rotate_field_key(proxy_user, inbounds, settings, monkeypatch):
    old_key = settings.OSTIUM_FIELD_KEY
    new_key = base64.b64encode(b"n" * 32).decode()
    old_password = proxy_user.password
    try:
        call_command("rotate_field_key", "--new-key", new_key, "--yes", stdout=io.StringIO())
        settings.OSTIUM_FIELD_KEY = new_key
        proxy_user.refresh_from_db()
        assert proxy_user.password == old_password
        assert proxy_user.reveal_subscription_token()
        from ostium.proxy.models import Inbound

        assert Inbound.objects.get(kind="vless").params["public_key"]
    finally:
        settings.OSTIUM_FIELD_KEY = old_key


@pytest.mark.django_db
def test_rotate_field_key_rejects_bad_key(settings):
    with pytest.raises(Exception):
        call_command("rotate_field_key", "--new-key", "bad", "--yes", stdout=io.StringIO())


class RestoreTests(TransactionTestCase):
    def test_full_restore(self):
        from ostium import paths
        from ostium.operations.backup import create_backup, restore_file
        from ostium.proxy.services import create_proxy_user

        user, _token = create_proxy_user("restore-me", quota_bytes=1024)
        backup = create_backup(password="a-long-backup-password")
        user.name = "changed"
        user.save()
        assert ProxyUser.objects.filter(name="changed").exists()
        restore_file(paths.backups_dir() / backup.filename, password="a-long-backup-password")
        assert ProxyUser.objects.filter(name="restore-me").exists()


@pytest.mark.django_db(transaction=True)
def test_restore_failure_restores_previous_database(settings, tmp_path):
    import hashlib
    import json
    import os
    import tarfile
    from io import BytesIO

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from ostium.operations.backup import MAGIC, BackupError, _derive, restore_file
    from ostium.proxy.services import create_proxy_user

    settings.OSTIUM_DATA_DIR = str(tmp_path)
    create_proxy_user("keep-me")

    database = b"this is not a Django fixture"
    manifest = {
        "format": 1,
        "product": "ostium-server",
        "version": "0.2.3",
        "field_key": settings.OSTIUM_FIELD_KEY,
        "database_sha256": hashlib.sha256(database).hexdigest(),
    }
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in (
            ("manifest.json", json.dumps(manifest).encode()),
            ("database.json", database),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, BytesIO(content))

    salt = os.urandom(16)
    nonce = os.urandom(12)
    payload = buffer.getvalue()
    path = tmp_path / "bad-restore.ostb"
    path.write_bytes(
        MAGIC + salt + nonce + AESGCM(_derive("a-long-backup-password", salt)).encrypt(nonce, payload, MAGIC)
    )

    with pytest.raises(BackupError, match="previous database was restored"):
        restore_file(path, password="a-long-backup-password")
    assert ProxyUser.objects.filter(name="keep-me").exists()
