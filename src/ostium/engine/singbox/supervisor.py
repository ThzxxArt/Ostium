"""Privileged core supervisor: validates, supervises and reloads sing-box."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ostium.config import Settings
from ostium.engine.singbox.config import config_digest
from ostium.engine.singbox.validate import validate_config
from ostium.util.redact import redact
from ostium.util.time import iso, utcnow

MAX_LOG_BYTES = 10 * 1024 * 1024


class CoreError(Exception):
    status_code = 500
    code = "core_error"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class EngineUnavailable(CoreError):
    status_code = 503
    code = "engine_unavailable"


class EngineCheckFailed(CoreError):
    status_code = 422
    code = "engine_check_failed"


class EngineStartFailed(CoreError):
    status_code = 500
    code = "engine_start_failed"


@dataclass
class SupervisorStatus:
    running: bool
    pid: int | None
    revision: str | None
    config_sha256: str | None
    started_at: str | None
    updated_at: str | None
    last_error: str | None
    log_path: str
    engine_path: str
    engine_version: str


class CoreSupervisor:
    """Owns the sing-box child process and the last-good configuration."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.paths = settings.paths
        self.engine = Path(settings.engine_path or self.paths.engine_binary)
        self.last_good = self.paths.last_good_path
        self.state_path = self.paths.core_state_path
        self.log_path = self.paths.logs_dir / "core.log"
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._last_error: str | None = None
        self._started_at: datetime | None = None
        self._running_config_sha: str | None = None

    async def start(self) -> None:
        self.paths.ensure()
        self._rotate_logs()
        if not self.last_good.is_file():
            return
        try:
            raw = self.last_good.read_bytes()
            config = json.loads(raw)
            validate_config(
                config,
                role=self.settings.role,
                allowed_ports=set(self.settings.proxy_ports),
                allowed_paths=[self.paths.data_dir, self.paths.certs_dir],
                tun_interface=self.settings.tun_interface,
            )
        except Exception as exc:
            self._last_error = f"last-good config rejected: {exc}"
            self._write_state()
            return
        await self._spawn()
        self._running_config_sha = config_digest(config)

    async def apply(self, config: dict[str, Any], expected_sha256: str) -> SupervisorStatus:
        if not self.engine.is_file():
            raise EngineUnavailable(
                f"sing-box was not found at {self.engine}; install the Ostium core first"
            )
        actual = config_digest(config)
        if actual != expected_sha256:
            raise EngineCheckFailed(
                "configuration digest does not match the payload", "digest_mismatch"
            )
        validate_config(
            config,
            role=self.settings.role,
            allowed_ports=set(self.settings.proxy_ports),
            allowed_paths=[self.paths.data_dir, self.paths.certs_dir],
            tun_interface=self.settings.tun_interface,
        )
        async with self._lock:
            temp = self.last_good.with_suffix(".json.tmp")
            temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            if os.name == "posix":
                temp.chmod(0o600)
            try:
                await self._check(temp)
                temp.replace(self.last_good)
                if os.name == "posix":
                    self.last_good.chmod(0o600)
                if self._process is not None and self._process.returncode is None:
                    await self._reload_running()
                else:
                    await self._spawn()
                self._running_config_sha = actual
                self._last_error = None
            except CoreError:
                temp.unlink(missing_ok=True)
                self._write_state()
                raise
            except Exception as exc:
                temp.unlink(missing_ok=True)
                self._last_error = redact(str(exc))
                self._write_state()
                raise EngineStartFailed(f"failed to apply configuration: {exc}") from exc
            self._write_state()
            return self.status()

    async def reload(self) -> SupervisorStatus:
        if not self.last_good.is_file():
            raise EngineUnavailable("no last-good configuration is available")
        if not self.engine.is_file():
            raise EngineUnavailable(f"sing-box was not found at {self.engine}")
        async with self._lock:
            if self._process is not None and self._process.returncode is None:
                await self._reload_running()
            else:
                await self._spawn()
            self._write_state()
        return self.status()

    async def stop_process(self) -> SupervisorStatus:
        async with self._lock:
            await self._terminate()
            self._write_state()
        return self.status()

    async def shutdown(self) -> None:
        async with self._lock:
            await self._terminate()

    def status(self) -> SupervisorStatus:
        pid = (
            self._process.pid
            if self._process is not None and self._process.returncode is None
            else None
        )
        revision = None
        if self.last_good.is_file():
            try:
                revision = config_digest(json.loads(self.last_good.read_bytes()))[:16]
            except Exception:
                revision = None
        return SupervisorStatus(
            running=pid is not None,
            pid=pid,
            revision=revision,
            config_sha256=self._running_config_sha,
            started_at=iso(self._started_at),
            updated_at=iso(utcnow()),
            last_error=self._last_error,
            log_path=str(self.log_path),
            engine_path=str(self.engine),
            engine_version=self.settings.engine_version,
        )

    def read_logs(self, tail: int = 500) -> str:
        if not self.log_path.is_file():
            return ""
        tail = max(1, min(tail, 5000))
        with self.log_path.open("r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()[-tail:]
        return redact("".join(lines))

    async def _check(self, config_path: Path) -> None:
        command = [str(self.engine), "check", "-c", str(config_path)]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        except FileNotFoundError as exc:
            raise EngineUnavailable(f"sing-box was not found at {self.engine}") from exc
        except TimeoutError as exc:
            raise EngineCheckFailed("sing-box check timed out") from exc
        if process.returncode != 0:
            detail = (stderr or stdout).decode("utf-8", errors="replace").strip()
            raise EngineCheckFailed(redact(detail[-4000:] or "sing-box check failed"))
        self._append_log("check", (stdout or b"").decode("utf-8", errors="replace"))

    async def _spawn(self) -> None:
        if not self.engine.is_file():
            raise EngineUnavailable(f"sing-box was not found at {self.engine}")
        await self._terminate()
        if not self.last_good.is_file():
            raise EngineUnavailable("no last-good configuration is available")
        self._rotate_logs()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.log_path.open("ab", buffering=0)
        command = [str(self.engine), "run", "-c", str(self.last_good)]
        kwargs: dict[str, Any] = {
            "stdout": handle,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
        }
        if os.name == "posix":
            kwargs["start_new_session"] = True
        else:  # pragma: no cover - exercised on Windows
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = await asyncio.create_subprocess_exec(*command, **kwargs)
        except OSError as exc:
            handle.close()
            raise EngineStartFailed(f"could not start sing-box: {exc}") from exc
        finally:
            try:
                handle.close()
            except Exception:
                pass
        await asyncio.sleep(0.6)
        if process.returncode is not None:
            detail = self.read_logs(80)
            self._last_error = detail or f"sing-box exited with code {process.returncode}"
            raise EngineStartFailed(self._last_error)
        self._process = process
        self._started_at = utcnow()
        self._last_error = None
        self._append_log("supervisor", f"started sing-box pid={process.pid}")

    async def _reload_running(self) -> None:
        assert self._process is not None
        if os.name == "posix":
            self._process.send_signal(signal.SIGHUP)
            await asyncio.sleep(0.5)
            if self._process.returncode is not None:
                self._last_error = self.read_logs(80) or "sing-box exited after reload"
                await self._spawn()
            else:
                self._append_log("supervisor", "reloaded via SIGHUP")
            return
        # sing-box does not handle SIGHUP on Windows; restart the child instead.
        await self._spawn()

    async def _terminate(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            self._process = None
            return
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=10)
        except TimeoutError:
            process.kill()
            await process.wait()
        except ProcessLookupError:
            pass
        finally:
            self._process = None
            self._append_log("supervisor", "stopped sing-box")

    def _rotate_logs(self) -> None:
        try:
            if self.log_path.exists() and self.log_path.stat().st_size > MAX_LOG_BYTES:
                rotated = self.log_path.with_suffix(".log.1")
                rotated.unlink(missing_ok=True)
                self.log_path.rename(rotated)
        except OSError:
            pass

    def _append_log(self, source: str, message: str) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = utcnow().isoformat()
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{timestamp} [{source}] {redact(message, redact_ids=False)}\n")
        except OSError:
            pass

    def _write_state(self) -> None:
        status = self.status()
        payload = {
            "running": status.running,
            "pid": status.pid,
            "revision": status.revision,
            "config_sha256": status.config_sha256,
            "started_at": status.started_at,
            "updated_at": status.updated_at,
            "last_error": status.last_error,
            "engine_version": status.engine_version,
        }
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            if os.name == "posix":
                self.state_path.chmod(0o600)
        except OSError:
            pass


def ensure_core_token(path: Path) -> str:
    """Create or read the shared core API token."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    import secrets

    token = secrets.token_urlsafe(48)
    path.write_text(token, encoding="utf-8")
    if os.name == "posix":
        path.chmod(0o600)
    return token
