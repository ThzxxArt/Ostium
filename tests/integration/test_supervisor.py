"""Supervisor process lifecycle tests with a fake binary."""

from __future__ import annotations

import os
import stat

import pytest

from ostium.engine import supervisor as supervisor_module
from ostium.engine.supervisor import (
    Supervisor,
    SupervisorError,
    binary_version,
    disk_free_bytes,
    terminate_orphans,
    verify_binary,
)


@pytest.fixture
def fake_binary(tmp_path):
    path = tmp_path / "sing-box"
    path.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "version" ]; then echo "sing-box version 1.14.4"; exit 0; fi\n'
        "trap 'exit 0' TERM INT\n"
        "while true; do sleep 0.05; done\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def configure_binary(settings, fake_binary):
    settings.OSTIUM_SINGBOX_PATH = str(fake_binary)
    settings.OSTIUM_SINGBOX_BINARY_SHA256 = ""
    return fake_binary


def test_verify_binary(configure_binary):
    ok, message = verify_binary()
    assert ok is True
    assert message == "sing-box version 1.14.4"
    assert binary_version() == "1.14.4"


def test_verify_binary_missing(settings, tmp_path):
    settings.OSTIUM_SINGBOX_PATH = str(tmp_path / "missing")
    ok, message = verify_binary()
    assert ok is False
    assert "not found" in message


def test_verify_binary_hash_mismatch(configure_binary, settings):
    settings.OSTIUM_SINGBOX_BINARY_SHA256 = "0" * 64
    ok, message = verify_binary()
    assert ok is False
    assert "SHA256" in message


def test_supervisor_lifecycle(configure_binary, tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{}")
    supervisor = Supervisor(log_path=tmp_path / "sing-box.log")
    pid = supervisor.start(config)
    assert pid > 0
    assert supervisor.running
    assert supervisor.pid == pid
    with pytest.raises(SupervisorError):
        supervisor.start(config)
    supervisor.restart(config)
    assert supervisor.running
    supervisor.stop()
    assert supervisor.running is False
    supervisor.stop()


def test_supervisor_start_failure(settings, tmp_path):
    settings.OSTIUM_SINGBOX_PATH = str(tmp_path / "missing")
    supervisor = Supervisor(log_path=tmp_path / "log")
    with pytest.raises(SupervisorError):
        supervisor.start(tmp_path / "config.json")


def test_supervisor_context_manager(configure_binary, tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{}")
    with Supervisor(log_path=tmp_path / "log") as supervisor:
        supervisor.start(config)
        assert supervisor.running
    assert supervisor.running is False


def test_terminate_orphans(monkeypatch, settings, tmp_path):
    from ostium import paths

    settings.OSTIUM_DATA_DIR = str(tmp_path)

    class FakeProc:
        def __init__(self, pid=1):
            self.pid = pid
            self.info = {
                "pid": pid,
                "name": "sing-box",
                "cmdline": ["sing-box", "run", "-c", str(paths.config_path())],
                "exe": "/usr/bin/sing-box",
            }
            self.terminated = False
            self.killed = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.killed = True

    proc = FakeProc()
    monkeypatch.setattr(supervisor_module.psutil, "process_iter", lambda fields: [proc])
    killed = terminate_orphans()
    assert proc.terminated is True
    assert killed == [1]


def test_disk_free():
    assert disk_free_bytes() > 0


def test_binary_not_executable(settings, tmp_path):
    path = tmp_path / "sing-box"
    path.write_text("#!/bin/sh\n")
    settings.OSTIUM_SINGBOX_PATH = str(path)
    ok, message = verify_binary()
    assert ok is False
    assert "executable" in message
    os.chmod(path, 0o700)
