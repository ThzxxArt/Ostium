"""Privileged core supervisor: validates, supervises and reloads sing-box."""

from __future__ import annotations

import asyncio
import json
import os
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
MAX_LOG_READ_BYTES = 2 * 1024 * 1024


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
    status_code = 502
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
        persisted_lan = self._read_persisted_allow_lan()
        try:
            raw = self.last_good.read_bytes()
            config = json.loads(raw)
            validate_config(
                config,
                role=self.settings.role,
                allowed_ports=set(self.settings.proxy_ports),
                allowed_paths=[self.paths.data_dir, self.paths.certs_dir],
                tun_interface=self.settings.tun_interface,
                # Re-validating a last-good file must reproduce the policy that
                # was persisted when it was accepted.  Missing metadata (an
                # upgraded 0.1.0 runtime) defaults to the safe value: LAN off.
                allow_lan=persisted_lan,
            )
        except Exception as exc:
            self._last_error = f"last-good config rejected: {exc}"
            self._write_state()
            return
        try:
            await self._spawn()
            self._running_config_sha = config_digest(config)
        except CoreError as exc:
            self._last_error = str(exc)
            self._write_state()

    async def apply(
        self,
        config: dict[str, Any],
        expected_sha256: str,
        *,
        allow_lan: bool = False,
        allowed_ports: set[int] | None = None,
    ) -> SupervisorStatus:
        if not self.engine.is_file():
            raise EngineUnavailable(
                f"sing-box was not found at {self.engine}; install the Ostium core first"
            )
        actual = config_digest(config)
        if actual != expected_sha256:
            raise EngineCheckFailed(
                "configuration digest does not match the payload", "digest_mismatch"
            )
        if allowed_ports is None:
            allowed_ports = set(self.settings.proxy_ports)
        validate_config(
            config,
            role=self.settings.role,
            allowed_ports=allowed_ports,
            allowed_paths=[self.paths.data_dir, self.paths.certs_dir],
            tun_interface=self.settings.tun_interface,
            allow_lan=allow_lan,
        )
        async with self._lock:
            temp = self.last_good.with_suffix(".json.tmp")
            temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            if os.name == "posix":
                temp.chmod(0o600)
            previous = self.last_good.read_bytes() if self.last_good.is_file() else None
            previous_meta = (
                self.paths.last_good_meta_path.read_bytes()
                if self.paths.last_good_meta_path.is_file()
                else None
            )
            replaced = False
            try:
                await self._check(temp)
                temp.replace(self.last_good)
                replaced = True
                if os.name == "posix":
                    self.last_good.chmod(0o600)
                self._write_meta(allow_lan)
                if self._process is not None and self._process.returncode is None:
                    # A SIGHUP only proves the signal was delivered, not that
                    # the new configuration is active.  Restart and verify.
                    await self._reload_running()
                else:
                    await self._spawn()
                self._running_config_sha = actual
                self._last_error = None
            except CoreError:
                temp.unlink(missing_ok=True)
                if replaced:
                    await self._rollback(previous, previous_meta)
                self._write_state()
                raise
            except Exception as exc:
                temp.unlink(missing_ok=True)
                if replaced:
                    await self._rollback(previous, previous_meta)
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

    def read_logs(self, tail: int = 500, *, max_bytes: int = MAX_LOG_READ_BYTES) -> str:
        if not self.log_path.is_file():
            return ""
        tail = max(1, min(tail, 5000))
        max_bytes = max(1, max_bytes)
        try:
            size = self.log_path.stat().st_size
            read_bytes = min(size, max_bytes)
            with self.log_path.open("rb") as handle:
                if size > read_bytes:
                    handle.seek(size - read_bytes)
                raw = handle.read(read_bytes)
        except OSError:
            return ""
        if size > read_bytes and b"\n" in raw:
            # Drop the first, possibly partial, line.
            raw = raw.split(b"\n", 1)[1]
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()[-tail:]
        return redact("\n".join(lines)) + ("\n" if lines else "")

    def enforce_log_limit(self, *, max_bytes: int = MAX_LOG_BYTES) -> bool:
        """Cap a long-running core log without restarting sing-box.

        sing-box keeps its log descriptor open with O_APPEND; truncating the
        file is safe because its next write starts at the new end.  This is the
        only way to bound the log between configuration reloads, which may be
        days apart.
        """

        try:
            size = self.log_path.stat().st_size
            if size <= max(1, max_bytes):
                return False
            with self.log_path.open("r+b") as handle:
                handle.truncate(0)
            self._append_log("supervisor", "truncated the core log after reaching its size limit")
            return True
        except OSError:
            return False

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
        self._cleanup_orphan()
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
        # A second observation catches configurations that pass the initial
        # grace period but fail while binding TUN ports or loading rule sets.
        await asyncio.sleep(0.3)
        if process.returncode is not None:
            detail = self.read_logs(80)
            self._last_error = detail or f"sing-box exited with code {process.returncode}"
            raise EngineStartFailed(self._last_error)
        self._process = process
        self._started_at = utcnow()
        self._last_error = None
        self._append_log("supervisor", f"started sing-box pid={process.pid}")

    async def _rollback(self, previous: bytes | None, previous_meta: bytes | None) -> None:
        """Restore the previous last-good config and start it again."""

        if previous is None:
            self.last_good.unlink(missing_ok=True)
            self.paths.last_good_meta_path.unlink(missing_ok=True)
            await self._terminate()
            return
        self.last_good.write_bytes(previous)
        if os.name == "posix":
            self.last_good.chmod(0o600)
        if previous_meta is None:
            self.paths.last_good_meta_path.unlink(missing_ok=True)
        else:
            self.paths.last_good_meta_path.write_bytes(previous_meta)
        try:
            await self._spawn()
            self._append_log("supervisor", "rollback to previous configuration")
        except Exception as exc:
            self._last_error = f"rollback failed: {exc}"
            self._append_log("supervisor", self._last_error)
        self._running_config_sha = config_digest(json.loads(previous))

    async def _reload_running(self) -> None:
        assert self._process is not None
        # sing-box offers no verifiable "configuration revision" handshake on
        # SIGHUP, so a successful signal would be reported as success even if
        # the new config was rejected.  Restart the child and verify liveness.
        await self._spawn()
        self._append_log("supervisor", "restarted sing-box to apply configuration")

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

    def _cleanup_orphan(self) -> None:
        """Terminate a sing-box child left behind by a killed core process.

        The child is started in a new session so an operator-run core that is
        SIGKILLed does not take its proxy down with it.  On the next start the
        old PID is still recorded in ``core-state.json`` and would otherwise
        keep the inbound ports, making every new spawn fail.
        """

        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            pid = int(state.get("pid") or 0)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return
        if pid <= 1 or pid == os.getpid():
            return
        try:
            import psutil

            process = psutil.Process(pid)
            command = " ".join(process.cmdline())
            if str(self.engine) not in command:
                return
            process.terminate()
            try:
                process.wait(timeout=5)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            self._append_log("supervisor", f"terminated orphan sing-box pid={pid}")
        except Exception:
            return

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

    def _read_persisted_allow_lan(self) -> bool:
        path = self.paths.last_good_meta_path
        if not path.is_file():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return bool(payload.get("allow_lan", False))

    def _write_meta(self, allow_lan: bool) -> None:
        payload = {
            "allow_lan": bool(allow_lan),
            "updated_at": iso(utcnow()),
        }
        path = self.paths.last_good_meta_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if os.name == "posix":
            path.chmod(0o600)

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
