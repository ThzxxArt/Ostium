"""Worker main loop and maintenance branches."""

from __future__ import annotations

import pytest

from ostium.engine import worker as worker_module
from ostium.engine.worker import Worker
from ostium.operations.models import RuntimeState


class FakeSupervisor:
    running = False
    pid = None
    binary = "/bin/true"

    def start(self, path):
        self.running = True
        self.pid = 111
        return self.pid

    def stop(self, timeout=10.0):
        self.running = False
        self.pid = None


@pytest.mark.django_db
def test_run_success(monkeypatch, tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    monkeypatch.setattr(worker_module, "verify_binary", lambda: (True, "sing-box version test"))
    monkeypatch.setattr(worker_module, "terminate_orphans", lambda: [])
    monkeypatch.setattr(Worker, "_loop", lambda self: None)
    monkeypatch.setattr(Worker, "_apply", lambda self, force=False: True)
    worker = Worker()
    worker.supervisor = FakeSupervisor()
    assert worker.run() == 0
    assert not (tmp_path / "runtime" / "worker.pid").exists()


@pytest.mark.django_db
def test_run_rejects_bad_binary(monkeypatch, tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    monkeypatch.setattr(worker_module, "verify_binary", lambda: (False, "missing"))
    assert Worker().run() == 1


@pytest.mark.django_db
def test_run_lock_conflict(monkeypatch, tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    holder = Worker()
    assert holder._acquire_lock() is True
    monkeypatch.setattr(worker_module, "verify_binary", lambda: (True, "ok"))
    try:
        assert Worker().run() == 1
    finally:
        holder._release_lock()


@pytest.mark.django_db
def test_loop_ticks(monkeypatch, tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    RuntimeState.load()
    RuntimeState.objects.filter(pk=1).update(desired_revision=2, applied_revision=0)
    worker = Worker()
    worker.supervisor = FakeSupervisor()
    worker.sampler.sample = lambda: True
    worker.sampler.flush = lambda: 0
    calls = {"apply": 0, "maintenance": 0}

    def fake_apply(force=False):
        calls["apply"] += 1
        RuntimeState.objects.filter(pk=1).update(applied_revision=2)
        return True

    monkeypatch.setattr(worker, "_apply", fake_apply)
    monkeypatch.setattr(worker, "_maintenance", lambda: calls.__setitem__("maintenance", calls["maintenance"] + 1))
    monkeypatch.setattr(worker.stop_event, "wait", lambda timeout: calls["apply"] >= 1)
    worker._loop()
    assert calls["apply"] == 1
    assert calls["maintenance"] == 1


@pytest.mark.django_db
def test_loop_watchdog(monkeypatch, tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "config.json").write_text("{}")
    worker = Worker()
    worker.supervisor = FakeSupervisor()
    worker.sampler.sample = lambda: True
    worker.sampler.flush = lambda: 0
    called = {"watchdog": 0}
    monkeypatch.setattr(worker, "_watchdog", lambda: called.__setitem__("watchdog", called["watchdog"] + 1))
    monkeypatch.setattr(worker, "_maintenance", lambda: None)
    monkeypatch.setattr(worker.stop_event, "wait", lambda timeout: called["watchdog"] >= 1)
    worker._loop()
    assert called["watchdog"] == 1


@pytest.mark.django_db
def test_maintenance_runs_all(monkeypatch, tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    worker = Worker()
    calls = []
    for name in ("_check_certificates", "_check_disk", "_retention", "_maybe_backup"):
        monkeypatch.setattr(worker, name, lambda name=name: calls.append(name))
    worker._maintenance()
    assert set(calls) == {"_check_certificates", "_check_disk", "_retention", "_maybe_backup"}


@pytest.mark.django_db
def test_maybe_backup_success(monkeypatch, tmp_path, settings):
    from constance import config

    settings.OSTIUM_DATA_DIR = str(tmp_path)
    config.auto_backup_enabled = True
    monkeypatch.setenv("OSTIUM_BACKUP_PASSWORD", "a-long-backup-password")
    import ostium.operations.backup as backup_module
    from ostium.operations.models import Backup

    calls = []
    monkeypatch.setattr(
        backup_module,
        "create_backup",
        lambda **kwargs: calls.append(kwargs) or Backup.objects.create(filename="auto.ostb", note="auto:worker"),
    )
    Worker()._maybe_backup()
    assert calls
