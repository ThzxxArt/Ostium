"""Worker apply/rollback tests with a fake supervisor."""

from __future__ import annotations

from pathlib import Path

import pytest

from ostium.engine import worker as worker_module
from ostium.engine.config import ConfigResult
from ostium.engine.worker import Worker
from ostium.operations.models import RuntimeState


class FakeSupervisor:
    def __init__(self):
        self.running = False
        self.pid = None
        self.binary = Path("/bin/true")
        self.started: list[Path] = []
        self.fail_starts = 0

    def start(self, path):
        self.started.append(path)
        if self.fail_starts:
            self.fail_starts -= 1
            raise worker_module.SupervisorError("boom")
        self.running = True
        self.pid = 1234
        return self.pid

    def stop(self, timeout: float = 10.0):
        self.running = False
        self.pid = None


def _result() -> ConfigResult:
    return ConfigResult(config={"log": {}}, sha256="a" * 64, effective_dns="doh")


@pytest.mark.django_db
def test_apply_success(monkeypatch, tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    state = RuntimeState.load()
    RuntimeState.objects.filter(pk=1).update(desired_revision=5)
    monkeypatch.setattr(worker_module, "generate_config", lambda probe_dns=True: _result())
    monkeypatch.setattr(worker_module, "check_config", lambda binary, path: (True, ""))
    monkeypatch.setattr(worker_module.time, "sleep", lambda seconds: None)
    worker = Worker()
    worker.supervisor = FakeSupervisor()
    assert worker._apply(force=True) is True
    state.refresh_from_db()
    assert state.applied_revision == 5
    assert state.singbox_running is True
    assert worker.supervisor.started


@pytest.mark.django_db
def test_apply_check_failure_keeps_state(monkeypatch, tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    RuntimeState.objects.filter(pk=1).update(desired_revision=2)
    monkeypatch.setattr(worker_module, "generate_config", lambda probe_dns=True: _result())
    monkeypatch.setattr(worker_module, "check_config", lambda binary, path: (False, "bad config"))
    worker = Worker()
    worker.supervisor = FakeSupervisor()
    assert worker._apply(force=True) is False
    state = RuntimeState.load()
    assert "bad config" in state.last_error
    assert state.singbox_running is False


@pytest.mark.django_db
def test_apply_generation_failure(monkeypatch, tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)

    def fail(probe_dns=True):
        raise worker_module.ConfigError("nope", errors=["missing certificate"])

    monkeypatch.setattr(worker_module, "generate_config", fail)
    worker = Worker()
    worker.supervisor = FakeSupervisor()
    assert worker._apply(force=True) is False
    assert "missing certificate" in RuntimeState.load().last_error


@pytest.mark.django_db
def test_apply_rollback(monkeypatch, tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    RuntimeState.objects.filter(pk=1).update(desired_revision=3)
    monkeypatch.setattr(worker_module, "generate_config", lambda probe_dns=True: _result())
    monkeypatch.setattr(worker_module, "check_config", lambda binary, path: (True, ""))
    monkeypatch.setattr(worker_module.time, "sleep", lambda seconds: None)
    config_path = tmp_path / "runtime" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('{"old": true}')
    worker = Worker()
    supervisor = FakeSupervisor()
    supervisor.fail_starts = 1
    worker.supervisor = supervisor
    assert worker._apply(force=True) is False
    assert len(supervisor.started) == 2
    assert "Rolled back" in RuntimeState.load().last_error
