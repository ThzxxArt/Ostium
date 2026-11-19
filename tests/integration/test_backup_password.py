"""Backup password file and settings-page coverage."""

from __future__ import annotations

import stat

import pytest
from django.urls import reverse

from ostium import paths
from ostium.operations.backup import (
    BackupError,
    backup_password_source,
    clear_backup_password,
    get_backup_password,
    save_backup_password,
)


@pytest.mark.django_db
def test_backup_password_file_round_trip(settings, tmp_path, monkeypatch):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    monkeypatch.delenv("OSTIUM_BACKUP_PASSWORD", raising=False)
    save_backup_password("a-long-backup-password")
    assert get_backup_password() == "a-long-backup-password"
    assert backup_password_source() == "file"
    path = paths.backup_password_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "a-long-backup-password" not in path.parent.name
    clear_backup_password()
    assert get_backup_password() == ""
    assert backup_password_source() == ""
    with pytest.raises(BackupError):
        save_backup_password("short")


@pytest.mark.django_db
def test_environment_password_has_priority(settings, tmp_path, monkeypatch):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    save_backup_password("file-backup-password")
    monkeypatch.setenv("OSTIUM_BACKUP_PASSWORD", "env-backup-password")
    assert get_backup_password() == "env-backup-password"
    assert backup_password_source() == "env"


@pytest.mark.django_db
def test_settings_page_saves_backup_password(admin_client, settings, tmp_path, monkeypatch):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    monkeypatch.delenv("OSTIUM_BACKUP_PASSWORD", raising=False)
    response = admin_client.post(
        reverse("console:settings"),
        {
            "action": "save_backup_password",
            "password": "a-long-backup-password",
            "confirm": "a-long-backup-password",
        },
    )
    assert response.status_code == 302
    assert get_backup_password() == "a-long-backup-password"


@pytest.mark.django_db
def test_settings_page_rejects_mismatched_backup_password(admin_client, settings, tmp_path):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    response = admin_client.post(
        reverse("console:settings"),
        {
            "action": "save_backup_password",
            "password": "a-long-backup-password",
            "confirm": "different-password",
        },
    )
    assert response.status_code == 200
    assert "两次输入的密码不一致" in response.content.decode()


@pytest.mark.django_db
def test_worker_uses_password_file(monkeypatch, settings, tmp_path):
    from constance import config

    from ostium.engine.worker import Worker
    from ostium.operations.models import Backup

    settings.OSTIUM_DATA_DIR = str(tmp_path)
    monkeypatch.delenv("OSTIUM_BACKUP_PASSWORD", raising=False)
    config.auto_backup_enabled = True
    save_backup_password("a-long-backup-password")
    import ostium.operations.backup as backup_module

    calls = []
    monkeypatch.setattr(
        backup_module,
        "create_backup",
        lambda **kwargs: calls.append(kwargs) or Backup.objects.create(filename="auto.ostb", note="auto:worker"),
    )
    Worker()._maybe_backup()
    assert calls
    assert calls[0]["password"] == "a-long-backup-password"


@pytest.mark.django_db
def test_dashboard_backup_check_uses_password_file(admin_client, settings, tmp_path, monkeypatch):
    from constance import config

    settings.OSTIUM_DATA_DIR = str(tmp_path)
    monkeypatch.delenv("OSTIUM_BACKUP_PASSWORD", raising=False)
    save_backup_password("a-long-backup-password")
    config.auto_backup_enabled = True
    response = admin_client.get(reverse("console:dashboard"))
    item = next(item for item in response.context["onboarding"] if item["key"] == "backup")
    assert item["done"] is True
