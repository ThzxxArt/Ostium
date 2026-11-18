"""Console failure branches and backup restore validation."""

from __future__ import annotations

import tarfile
from io import BytesIO

import pytest

from ostium.operations.backup import MAGIC, BackupError, _derive, restore_file


@pytest.mark.django_db
def test_user_detail_invalid_save(admin_client, proxy_user):
    other = __import__("ostium.proxy.services", fromlist=["create_proxy_user"]).create_proxy_user("other")[0]
    response = admin_client.post(
        f"/users/{proxy_user.pk}/",
        {
            "action": "save",
            "name": other.name,
            "quota": "10G",
            "quota_cycle": "total",
        },
    )
    assert response.status_code == 200
    assert b"already uses" in response.content


@pytest.mark.django_db
def test_inbounds_invalid_form(admin_client, inbounds):
    response = admin_client.post(
        "/inbounds/",
        {"kind": "vless", "vless-enabled": "on", "vless-port": "99999"},
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_connections_close_error(admin_client, monkeypatch):
    import ostium.operations.console_views as views
    from ostium.engine.clash import ClashError

    class Broken:
        def connections(self):
            return []

        def close_all(self):
            raise ClashError("down")

    monkeypatch.setattr(views, "ClashClient", lambda: Broken())
    response = admin_client.post("/connections/", {"action": "close_all"}, follow=True)
    assert response.status_code == 200
    assert b"down" in response.content


@pytest.mark.django_db
def test_certificate_missing(admin_client):
    response = admin_client.post("/certificates/", {"certificate_id": "00000000-0000-0000-0000-000000000000"})
    assert response.status_code == 404


@pytest.mark.django_db
def test_logs_empty(admin_client, settings, tmp_path):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    response = admin_client.get("/logs/?source=ostium")
    assert response.status_code == 200
    assert b"empty" in response.content.lower() or b"\xe8\xbf\x98\xe6\xb2\xa1\xe6\x9c\x89" in response.content


@pytest.mark.django_db
def test_system_backup_invalid(admin_client):
    response = admin_client.post("/system/", {"action": "backup", "password": "short"})
    assert response.status_code == 200


@pytest.mark.django_db
def test_jobs_empty(admin_client):
    assert admin_client.get("/jobs/").status_code == 200


def _encrypted(payload: bytes, password: str, settings) -> bytes:
    import os

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = os.urandom(16)
    nonce = os.urandom(12)
    return MAGIC + salt + nonce + AESGCM(_derive(password, salt)).encrypt(nonce, payload, MAGIC)


@pytest.mark.django_db
def test_restore_missing_manifest(tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("database.json")
        info.size = 2
        tar.addfile(info, BytesIO(b"{}"))
    path = tmp_path / "x.ostb"
    path.write_bytes(_encrypted(buffer.getvalue(), "a-long-backup-password", settings))
    with pytest.raises(BackupError):
        restore_file(path, password="a-long-backup-password")


@pytest.mark.django_db
def test_restore_checksum_mismatch(tmp_path, settings):
    import json

    settings.OSTIUM_DATA_DIR = str(tmp_path)
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in (
            ("manifest.json", json.dumps({"product": "ostium-server", "format": 1, "database_sha256": "0" * 64})),
            ("database.json", "[]"),
        ):
            raw = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            tar.addfile(info, BytesIO(raw))
    path = tmp_path / "y.ostb"
    path.write_bytes(_encrypted(buffer.getvalue(), "a-long-backup-password", settings))
    with pytest.raises(BackupError):
        restore_file(path, password="a-long-backup-password")
