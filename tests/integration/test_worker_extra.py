"""Additional worker maintenance and locking tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ostium.engine import worker as worker_module
from ostium.engine.worker import Worker
from ostium.operations.models import RuntimeState


class FakeSupervisor:
    def __init__(self):
        self.running = False
        self.pid = None
        self.binary = Path("/bin/true")
        self.start_error = None

    def start(self, path):
        if self.start_error:
            raise worker_module.SupervisorError(self.start_error)
        self.running = True
        self.pid = 4321
        return self.pid

    def stop(self, timeout: float = 10.0):
        self.running = False
        self.pid = None


@pytest.mark.django_db
def test_heartbeat_and_shutdown(tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    worker = Worker()
    worker.supervisor = FakeSupervisor()
    worker.supervisor.running = True
    worker.supervisor.pid = 99
    worker._heartbeat()
    state = RuntimeState.load()
    assert state.worker_heartbeat is not None
    assert state.singbox_pid == 99
    worker.shutdown()
    state.refresh_from_db()
    assert state.singbox_running is False


@pytest.mark.django_db
def test_retry_backoff():
    worker = Worker()
    worker._schedule_retry(7)
    assert worker.failed_revision == 7
    assert worker.next_retry_at is not None
    assert worker._retry_allowed(7) is False
    assert worker._retry_allowed(8) is True


@pytest.mark.django_db
def test_watchdog_restarts_existing_config(tmp_path, settings, monkeypatch):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    config_dir = tmp_path / "runtime"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{}")
    worker = Worker()
    worker.supervisor = FakeSupervisor()
    worker._watchdog()
    state = RuntimeState.load()
    assert state.singbox_running is True
    assert state.singbox_pid == 4321


@pytest.mark.django_db
def test_watchdog_marks_dirty_on_failure(tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    worker = Worker()
    supervisor = FakeSupervisor()
    supervisor.start_error = "cannot start"
    worker.supervisor = supervisor
    before = RuntimeState.load().desired_revision
    worker._watchdog()
    assert RuntimeState.load().desired_revision > before


@pytest.mark.django_db
def test_certificate_and_disk_maintenance(proxy_user, tmp_path, settings, monkeypatch):
    from ostium.certificates.services import generate_self_signed

    settings.OSTIUM_DATA_DIR = str(tmp_path)
    generate_self_signed("soon.example.com")
    worker = Worker()
    worker._check_certificates()
    monkeypatch.setattr(worker_module, "disk_free_bytes", lambda: 100)
    worker._check_disk()
    from ostium.operations.models import Alert

    assert Alert.objects.filter(code="disk_low").exists()


@pytest.mark.django_db
def test_retention_deletes_old_rows(tmp_path, settings):
    from datetime import date, timedelta

    from django.utils import timezone

    from ostium.operations.models import AuditEvent
    from ostium.proxy.models import TrafficDaily

    settings.OSTIUM_DATA_DIR = str(tmp_path)
    from constance import config

    config.traffic_retention_days = 1
    config.audit_retention_days = 1
    row = TrafficDaily.objects.create(
        user=__import__("ostium.proxy.services", fromlist=["create_proxy_user"]).create_proxy_user("old")[0],
        day=date.today() - timedelta(days=10),
        uplink=1,
        downlink=1,
    )
    AuditEvent.objects.create(action="old.event", created_at=timezone.now() - timedelta(days=10))
    Worker()._retention()
    assert not TrafficDaily.objects.filter(pk=row.pk).exists()
    assert not AuditEvent.objects.filter(action="old.event").exists()


@pytest.mark.django_db
def test_worker_lock(tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    worker = Worker()
    assert worker._acquire_lock() is True
    second = Worker()
    assert second._acquire_lock() is False
    worker._release_lock()


@pytest.mark.django_db
def test_auto_backup_requires_password(tmp_path, settings):
    from constance import config

    settings.OSTIUM_DATA_DIR = str(tmp_path)
    config.auto_backup_enabled = True
    import os

    old = os.environ.pop("OSTIUM_BACKUP_PASSWORD", None)
    try:
        Worker()._maybe_backup()
    finally:
        if old is not None:
            os.environ["OSTIUM_BACKUP_PASSWORD"] = old
    from ostium.operations.models import Alert

    assert Alert.objects.filter(code="backup_failed").exists()
