from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ostium.config import Role, Settings
from ostium.engine.singbox import supervisor as supervisor_module
from ostium.engine.singbox.config import (
    RealitySpec,
    ServerConfigSpec,
    ServerInbound,
    UserCredential,
    build_server_config,
    config_digest,
)
from ostium.engine.singbox.supervisor import (
    CoreSupervisor,
    EngineCheckFailed,
    EngineStartFailed,
    EngineUnavailable,
    ensure_core_token,
)
from ostium.engine.singbox.validate import ConfigRejected


def _settings(tmp_path: Path) -> Settings:
    value = Settings(
        role=Role.SERVER,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
        engine_path=str(tmp_path / "sing-box"),
        proxy_ports=[443, 8388],
        dev=True,
    )
    value.paths.ensure()
    return value


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def _good_script(path: Path) -> Path:
    return _script(
        path,
        """
if [ "$1" = "check" ]; then
  echo "check ok"
  exit 0
fi
if [ "$1" = "run" ]; then
  echo "run started"
  trap 'exit 0' HUP
  while true; do sleep 0.1; done
fi
exit 2
""",
    )


def _fail_run_script(path: Path) -> Path:
    return _script(
        path,
        """
if [ "$1" = "check" ]; then exit 0; fi
if [ "$1" = "run" ]; then echo "run failed" >&2; exit 7; fi
exit 2
""",
    )


def _fail_check_script(path: Path) -> Path:
    return _script(
        path,
        """
if [ "$1" = "check" ]; then echo "invalid config" >&2; exit 1; fi
exit 0
""",
    )


def _server_config() -> dict:
    return build_server_config(
        ServerConfigSpec(
            inbounds=[
                ServerInbound(
                    kind="vless",
                    enabled=True,
                    listen="127.0.0.1",
                    port=443,
                    reality=RealitySpec(private_key="private", short_id="short"),
                )
            ],
            users=[
                UserCredential(
                    name="alice",
                    uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
                    password="pw",
                    ss_password="ss",
                )
            ],
            clash_secret="secret",
            enable_v2ray_api=False,
        )
    )


def test_apply_reload_stop_and_start(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = _good_script(Path(settings.engine_path))  # type: ignore[arg-type]
        supervisor = CoreSupervisor(settings)
        config = _server_config()
        applied = await supervisor.apply(config, config_digest(config))
        assert applied.running is True
        assert applied.pid
        assert applied.revision
        assert settings.paths.last_good_path.is_file()
        assert settings.paths.core_state_path.is_file()
        assert "check ok" in supervisor.read_logs()
        assert "started" in supervisor.read_logs()

        reloaded = await supervisor.reload()
        assert reloaded.running is True

        stopped = await supervisor.stop_process()
        assert stopped.running is False
        assert supervisor.status().pid is None
        await supervisor.shutdown()

        # A fresh supervisor starts from the last-good configuration.
        second = CoreSupervisor(settings)
        await second.start()
        assert second.status().running is True
        await second.shutdown()

        settings.paths.last_good_path.unlink()
        third = CoreSupervisor(settings)
        await third.start()
        assert third.status().running is False

        with pytest.raises(EngineUnavailable):
            await third.reload()
        engine.unlink()
        with pytest.raises(EngineUnavailable):
            await third.apply(config, config_digest(config))

    asyncio.run(_run())


def test_apply_validation_errors(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        _good_script(Path(settings.engine_path))  # type: ignore[arg-type]
        supervisor = CoreSupervisor(settings)
        config = _server_config()

        with pytest.raises(EngineCheckFailed) as digest:
            await supervisor.apply(config, "0" * 64)
        assert digest.value.code == "digest_mismatch"

        with pytest.raises(ConfigRejected):
            await supervisor.apply({"inbounds": []}, config_digest({"inbounds": []}))

        settings.paths.last_good_path.write_text("{bad json")
        assert supervisor.status().revision is None

    asyncio.run(_run())


def test_start_rejects_invalid_last_good(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        _good_script(Path(settings.engine_path))  # type: ignore[arg-type]
        supervisor = CoreSupervisor(settings)
        settings.paths.last_good_path.write_text("not-json")
        await supervisor.start()
        status = supervisor.status()
        assert status.running is False
        assert "last-good config rejected" in (status.last_error or "")
        assert settings.paths.core_state_path.is_file()

    asyncio.run(_run())


def test_check_failure_preserves_last_good(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        _fail_check_script(Path(settings.engine_path))  # type: ignore[arg-type]
        supervisor = CoreSupervisor(settings)
        original = json.dumps(_server_config()).encode()
        settings.paths.last_good_path.write_bytes(original)
        config = _server_config()
        config["log"] = {"level": "debug"}
        with pytest.raises(EngineCheckFailed) as excinfo:
            await supervisor.apply(config, config_digest(config))
        assert "invalid config" in str(excinfo.value)
        assert settings.paths.last_good_path.read_bytes() == original
        assert not settings.paths.last_good_path.with_suffix(".json.tmp").exists()

    asyncio.run(_run())


def test_start_failure_without_previous_removes_last_good(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        _fail_run_script(Path(settings.engine_path))  # type: ignore[arg-type]
        supervisor = CoreSupervisor(settings)
        config = _server_config()
        with pytest.raises(EngineStartFailed) as excinfo:
            await supervisor.apply(config, config_digest(config))
        assert "run failed" in str(excinfo.value)
        assert not settings.paths.last_good_path.exists()
        status = supervisor.status()
        assert status.running is False

    asyncio.run(_run())


def test_start_failure_rolls_back_previous_config(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        script = _good_script(Path(settings.engine_path))  # type: ignore[arg-type]
        supervisor = CoreSupervisor(settings)
        config = _server_config()
        await supervisor.apply(config, config_digest(config))
        previous = settings.paths.last_good_path.read_bytes()

        _fail_run_script(script)
        changed = json.loads(json.dumps(config))
        changed["log"]["level"] = "debug"
        with pytest.raises(EngineStartFailed):
            await supervisor.apply(changed, config_digest(changed))
        assert settings.paths.last_good_path.read_bytes() == previous
        assert "rollback failed" in (supervisor.status().last_error or "")
        await supervisor.shutdown()

    asyncio.run(_run())


def test_start_and_apply_error_paths(tmp_path: Path, monkeypatch) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        _good_script(Path(settings.engine_path))  # type: ignore[arg-type]
        supervisor = CoreSupervisor(settings)
        settings.paths.last_good_path.write_text(json.dumps(_server_config()))

        async def fail_spawn() -> None:
            raise EngineStartFailed("spawn failed")

        supervisor._spawn = fail_spawn  # type: ignore[method-assign]
        await supervisor.start()
        assert "spawn failed" in (supervisor.status().last_error or "")

        # A non-Core exception during apply is converted to EngineStartFailed.
        config = _server_config()

        async def broken_check(path: Path) -> None:
            return None

        async def boom_spawn() -> None:
            raise RuntimeError("boom")

        supervisor._spawn = boom_spawn  # type: ignore[method-assign]
        monkeypatch.setattr(supervisor, "_check", broken_check)
        with pytest.raises(EngineStartFailed, match="failed to apply configuration"):
            await supervisor.apply(config, config_digest(config))

        # _check raises the expected domain errors.
        missing = CoreSupervisor(settings)
        missing.engine = tmp_path / "missing-binary"
        with pytest.raises(EngineUnavailable):
            await missing._check(settings.paths.last_good_path)

        async def timeout_wait(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise TimeoutError

        monkeypatch.setattr(supervisor_module.asyncio, "wait_for", timeout_wait)
        monkeypatch.setattr(supervisor_module.asyncio, "create_subprocess_exec", _fake_process)
        with pytest.raises(EngineCheckFailed, match="timed out"):
            await missing._check(settings.paths.last_good_path)

        # _spawn rejects a missing engine or missing last-good configuration.
        monkeypatch.undo()
        no_engine = CoreSupervisor(_settings(tmp_path / "no-engine"))
        no_engine.engine = tmp_path / "absent"
        with pytest.raises(EngineUnavailable):
            await no_engine._spawn()

        no_config = CoreSupervisor(_settings(tmp_path / "no-config"))
        Path(no_config.engine).write_text("x")
        with pytest.raises(EngineUnavailable, match="no last-good"):
            await no_config._spawn()

        # An OS error while spawning is wrapped.
        os_error = CoreSupervisor(_settings(tmp_path / "os-error"))
        Path(os_error.engine).write_text("x")
        os_error.last_good.write_text(json.dumps(_server_config()))

        async def os_fail(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise OSError("cannot exec")

        monkeypatch.setattr(supervisor_module.asyncio, "create_subprocess_exec", os_fail)
        with pytest.raises(EngineStartFailed, match="could not start"):
            await os_error._spawn()

    async def _fake_process(*args, **kwargs):  # type: ignore[no-untyped-def]
        process = FakeProcess()
        return process

    asyncio.run(_run())


def test_rollback_and_reload_branches(tmp_path: Path, monkeypatch) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        supervisor = CoreSupervisor(settings)
        previous = json.dumps(_server_config()).encode()
        supervisor.last_good.write_bytes(previous)
        process = FakeProcess()
        supervisor._process = process  # type: ignore[assignment]

        async def no_sleep(seconds):  # type: ignore[no-untyped-def]
            return None

        async def fake_spawn() -> None:
            supervisor._process = FakeProcess()

        monkeypatch.setattr(supervisor_module.asyncio, "sleep", no_sleep)
        monkeypatch.setattr(supervisor, "_spawn", fake_spawn)
        await supervisor._rollback(previous, None)
        assert "rollback to previous configuration" in supervisor.read_logs(10)
        assert supervisor._process is not process

        await supervisor._reload_running()
        assert "restarted sing-box" in supervisor.read_logs(10)
        assert supervisor._process is not process

        # reload without a configuration or engine.
        supervisor.last_good.unlink()
        with pytest.raises(EngineUnavailable):
            await supervisor.reload()
        supervisor.last_good.write_bytes(previous)
        Path(supervisor.engine).write_text("x")
        supervisor.engine = tmp_path / "missing"
        with pytest.raises(EngineUnavailable):
            await supervisor.reload()

        # reload after the process has stopped spawns a new one.
        supervisor.engine = Path(settings.engine_path)  # type: ignore[assignment]
        _good_script(supervisor.engine)
        supervisor._process = None

        async def fake_spawn() -> None:
            supervisor._process = FakeProcess()

        supervisor._spawn = fake_spawn  # type: ignore[method-assign]
        reloaded = await supervisor.reload()
        assert reloaded.running is True

        # Log rotation failures are swallowed.
        class BrokenPath:
            def exists(self):
                return True

            def stat(self):
                raise OSError("stat failed")

        supervisor.log_path = BrokenPath()  # type: ignore[assignment]
        supervisor._rotate_logs()

    asyncio.run(_run())


def test_read_logs_rotation_and_write_failures(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        supervisor = CoreSupervisor(settings)
        assert supervisor.read_logs() == ""

        settings.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        supervisor.log_path.write_text("line one token=abc\nline two\n")
        assert "token=[REDACTED]" in supervisor.read_logs(2)
        assert supervisor.read_logs(1).strip() == "line two"

        supervisor.log_path.write_bytes(b"x" * (supervisor_module.MAX_LOG_BYTES + 1))
        supervisor._rotate_logs()
        assert supervisor.log_path.with_suffix(".log.1").is_file()

        # Write failures must be swallowed (directory in place of a file).
        supervisor.log_path.unlink(missing_ok=True)
        rotated = supervisor.log_path.with_suffix(".log.1")
        rotated.unlink(missing_ok=True)
        supervisor.log_path.mkdir()
        supervisor._rotate_logs()
        supervisor._append_log("test", "boom")
        supervisor.state_path.mkdir(parents=True, exist_ok=True)
        supervisor._write_state()
        supervisor.log_path.rmdir()

    asyncio.run(_run())


def test_ensure_core_token(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "core.token"
    first = ensure_core_token(path)
    assert path.read_text().strip() == first
    assert ensure_core_token(path) == first
    path.write_text("   ")
    second = ensure_core_token(path)
    assert second != first
    if os.name == "posix":
        assert (path.stat().st_mode & 0o777) == 0o600


class FakeProcess:
    def __init__(self, pid: int = 123) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self.signals: list[int] = []
        self.wait_calls = 0
        self.wait_timeout = False

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def send_signal(self, signal: int) -> None:
        self.signals.append(signal)

    async def wait(self) -> int:
        self.wait_calls += 1
        if self.wait_timeout and self.wait_calls == 1:
            raise TimeoutError
        self.returncode = 0
        return 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""


def test_terminate_timeout_and_process_lookup(tmp_path: Path) -> None:
    async def _run() -> None:
        supervisor = CoreSupervisor(_settings(tmp_path))
        process = FakeProcess()
        process.wait_timeout = True
        supervisor._process = process  # type: ignore[assignment]
        await supervisor._terminate()
        assert process.killed is True
        assert supervisor._process is None

        class LookupProcess(FakeProcess):
            def terminate(self) -> None:
                raise ProcessLookupError

        lookup = LookupProcess()
        supervisor._process = lookup  # type: ignore[assignment]
        await supervisor._terminate()
        assert supervisor._process is None

        supervisor._process = lookup  # already exited
        lookup.returncode = 0
        await supervisor._terminate()
        assert supervisor._process is None

    asyncio.run(_run())


def test_windows_spawn_and_reload_branches(tmp_path: Path, monkeypatch) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        Path(settings.engine_path).write_text("x")  # type: ignore[arg-type]
        supervisor = CoreSupervisor(settings)
        settings.paths.last_good_path.write_text(json.dumps(_server_config()))
        created: list[FakeProcess] = []

        async def create(*args, **kwargs):  # type: ignore[no-untyped-def]
            process = FakeProcess(pid=456)
            created.append(process)
            return process

        monkeypatch.setattr(supervisor_module.asyncio, "create_subprocess_exec", create)
        monkeypatch.setattr(supervisor_module, "os", SimpleNamespace(name="nt", environ=os.environ))
        await supervisor._spawn()
        assert supervisor.status().running is True
        first = supervisor._process
        await supervisor._reload_running()
        assert supervisor._process is not first
        assert len(created) == 2
        await supervisor.shutdown()

    asyncio.run(_run())
