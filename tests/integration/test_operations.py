"""Health, backup and diagnostics tests."""

from __future__ import annotations

import tarfile
from io import BytesIO
from pathlib import Path

import pytest
from django.test import Client

from ostium.operations.backup import BackupError, create_backup, decrypt_archive, restore_file
from ostium.operations.diagnostics import build_diagnostics
from ostium.operations.models import RuntimeState


@pytest.mark.django_db
def test_health_endpoints():
    client = Client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    response = client.get("/readyz")
    assert response.status_code == 200
    assert set(response.json()["checks"]) == {"database", "worker", "singbox"}
    response = client.get("/metrics")
    assert response.status_code == 200
    assert b"ostium_worker_alive" in response.content


@pytest.mark.django_db
def test_health_view():
    response = Client().get("/health/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_backup_round_trip(proxy_user):
    backup = create_backup(password="a-long-backup-password", note="test")
    assert backup.encrypted is True
    assert backup.size > 0
    path = Path(backup.filename)
    from ostium import paths

    blob = (paths.backups_dir() / path).read_bytes()
    assert blob.startswith(b"OSTB1")
    payload = decrypt_archive(blob, "a-long-backup-password")
    with tarfile.open(fileobj=BytesIO(payload), mode="r:gz") as tar:
        names = tar.getnames()
    assert "manifest.json" in names
    assert "database.json" in names


@pytest.mark.django_db
def test_backup_rejects_short_password():
    with pytest.raises(BackupError):
        create_backup(password="short")


@pytest.mark.django_db
def test_backup_wrong_password(proxy_user):
    backup = create_backup(password="a-long-backup-password")
    from ostium import paths

    blob = (paths.backups_dir() / backup.filename).read_bytes()
    with pytest.raises(BackupError):
        decrypt_archive(blob, "another-long-password")


def test_restore_rejects_non_backup(tmp_path):
    path = tmp_path / "fake.ostb"
    path.write_bytes(b"not a backup")
    with pytest.raises(BackupError):
        restore_file(path, password="a-long-backup-password")


@pytest.mark.django_db
def test_diagnostics_bundle(proxy_user):
    payload = build_diagnostics()
    with tarfile.open(fileobj=BytesIO(payload), mode="r:gz") as tar:
        names = tar.getnames()
    assert "runtime.json" in names
    assert "system.json" in names
    assert "config.redacted.json" in names
    assert "logs/ostium.log" in names


@pytest.mark.django_db
def test_doctor_checks():
    from ostium.operations.doctor import doctor_summary, run_doctor

    checks = run_doctor()
    assert checks
    summary = doctor_summary(checks)
    assert summary["pass"] + summary["warn"] + summary["fail"] == len(checks)
    assert any(check["name"] == "Database" for check in checks)


@pytest.mark.django_db
def test_runtime_heartbeat():
    state = RuntimeState.load()
    assert state.worker_alive is False
    state.worker_heartbeat = __import__("django.utils.timezone", fromlist=["now"]).now()
    state.save()
    assert state.worker_alive is True
