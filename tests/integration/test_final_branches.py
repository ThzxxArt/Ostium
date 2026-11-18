"""Final regression branches."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from ostium.engine.worker import Worker
from ostium.operations.models import Backup


@pytest.mark.django_db
def test_retention_removes_auto_backup_file(tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    from ostium import paths

    paths.ensure()
    backup = Backup.objects.create(
        filename="old.ostb",
        note="auto:worker",
        created_at=timezone.now() - timedelta(days=40),
    )
    file = paths.backups_dir() / backup.filename
    file.write_bytes(b"x")
    Worker()._retention()
    assert not Backup.objects.filter(pk=backup.pk).exists()
    assert not file.exists()


@pytest.mark.django_db
def test_pending_user_accepts_authenticated_session(admin_user):
    from django.test import RequestFactory

    from ostium.accounts.views import _pending_user

    request = RequestFactory().get("/")
    request.user = admin_user
    request.session = {}
    assert _pending_user(request) is admin_user
