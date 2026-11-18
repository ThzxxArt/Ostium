"""More supervisor and worker branch coverage."""

from __future__ import annotations

import os
import signal
import stat
import time

import pytest

from ostium.engine import supervisor as supervisor_module
from ostium.engine import worker as worker_module
from ostium.engine.supervisor import Supervisor, SupervisorError, terminate_orphans, verify_binary
from ostium.engine.worker import Worker
from ostium.operations.models import RuntimeState


@pytest.mark.django_db
def test_start_process_exits_immediately(tmp_path, settings):
    binary = tmp_path / "sing-box"
    binary.write_text("#!/bin/sh\nexit 7\n")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    settings.OSTIUM_SINGBOX_PATH = str(binary)
    settings.OSTIUM_SINGBOX_BINARY_SHA256 = ""
    supervisor = Supervisor(log_path=tmp_path / "log")
    with pytest.raises(SupervisorError) as exc:
        supervisor.start(tmp_path / "config.json")
    assert "exited" in str(exc.value)


def test_verify_binary_nonzero(tmp_path, settings):
    binary = tmp_path / "sing-box"
    binary.write_text("#!/bin/sh\nexit 3\n")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    settings.OSTIUM_SINGBOX_PATH = str(binary)
    settings.OSTIUM_SINGBOX_BINARY_SHA256 = ""
    ok, _message = verify_binary()
    assert ok is False


def test_terminate_orphans_skips(monkeypatch):
    class Proc:
        def __init__(self, pid, cmdline, error=None):
            self.pid = pid
            self.info = {"pid": pid, "cmdline": cmdline, "exe": ""}
            self.error = error

        def terminate(self):
            if self.error:
                raise self.error

        def wait(self, timeout=None):
            return 0

    import psutil

    procs = [
        Proc(1, ["bash"]),
        Proc(2, []),
        Proc(3, ["sing-box", "run"], psutil.NoSuchProcess(3)),
        Proc(4, ["sing-box", "run"], psutil.AccessDenied(4)),
    ]
    monkeypatch.setattr(supervisor_module.psutil, "process_iter", lambda fields: procs)
    assert terminate_orphans(keep_pid=1) == []


def test_stop_after_external_kill(tmp_path, settings):
    binary = tmp_path / "sing-box"
    binary.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "version" ]; then echo "sing-box version 1"; exit 0; fi\n'
        "while true; do sleep 0.05; done\n"
    )
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    settings.OSTIUM_SINGBOX_PATH = str(binary)
    settings.OSTIUM_SINGBOX_BINARY_SHA256 = ""
    supervisor = Supervisor(log_path=tmp_path / "log")
    config = tmp_path / "config.json"
    config.write_text("{}")
    pid = supervisor.start(config)
    os.kill(pid, signal.SIGKILL)
    time.sleep(0.2)
    supervisor.stop()


@pytest.mark.django_db
def test_worker_run_initial_apply_failure(monkeypatch, tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    monkeypatch.setattr(worker_module, "verify_binary", lambda: (True, "ok"))
    monkeypatch.setattr(worker_module, "terminate_orphans", lambda: [1])
    monkeypatch.setattr(Worker, "_loop", lambda self: None)
    monkeypatch.setattr(Worker, "_apply", lambda self, force=False: False)
    assert Worker().run() == 0


@pytest.mark.django_db
def test_worker_apply_skips(monkeypatch, tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    from constance import config

    config.maintenance_mode = True
    worker = Worker()
    assert worker._apply(force=True) is False
    config.maintenance_mode = False
    RuntimeState.objects.filter(pk=1).update(desired_revision=0, applied_revision=0)
    path = tmp_path / "runtime"
    path.mkdir()
    (path / "config.json").write_text("{}")
    assert worker._apply(force=False) is True


@pytest.mark.django_db
def test_worker_record_failure(tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    worker = Worker()
    worker._record_failure("x" * 5000, 1)
    assert len(RuntimeState.load().last_error) == 4000


@pytest.mark.django_db
def test_worker_maybe_backup_recent(monkeypatch, tmp_path, settings):
    from constance import config

    from ostium.operations.models import Backup

    settings.OSTIUM_DATA_DIR = str(tmp_path)
    config.auto_backup_enabled = True
    monkeypatch.setenv("OSTIUM_BACKUP_PASSWORD", "a-long-backup-password")
    Backup.objects.create(filename="recent", note="auto:worker")
    Worker()._maybe_backup()
