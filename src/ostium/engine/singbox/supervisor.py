"""Privileged core supervisor: validates, supervises and reloads sing-box."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from ostium.config import Role, Settings
from ostium.engine.singbox.config import CONFIG_POLICY_VERSION, config_digest
from ostium.engine.singbox.validate import validate_config
from ostium.services.enforcement import EnforcementError, read_enforcement, strip_disabled_users
from ostium.util.redact import redact
from ostium.util.time import iso, utcnow

MAX_LOG_BYTES = 10 * 1024 * 1024
MAX_LOG_READ_BYTES = 2 * 1024 * 1024

# A client install runs the control plane and the privileged core as different
# users with different data directories.  Rule-set files therefore cannot be
# left in the UI data directory: the core cannot read it and its path
# allow-list rejects it.  The UI uploads the bytes with the apply request and
# the core materialises them inside its own runtime directory.
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_ARTIFACTS_TOTAL_BYTES = 32 * 1024 * 1024
MAX_ARTIFACTS = 32
_ARTIFACT_SUFFIXES = {".json", ".srs", ".db", ".txt", ".yaml", ".yml", ".mmdb"}

_PATH_KEYS = {
    "certificate_path",
    "key_path",
    "path",
    "client_certificate_path",
    "client_key_path",
}


def _collect_path_strings(value: Any, found: set[str], depth: int = 0) -> None:
    if depth > 40:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and isinstance(child, str):
                path_like = key.endswith(("_path", "_file")) and child.startswith("/")
                if key in _PATH_KEYS or path_like:
                    found.add(child)
            _collect_path_strings(child, found, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _collect_path_strings(child, found, depth + 1)


def _replace_strings(value: Any, replacements: dict[str, str], depth: int = 0) -> Any:
    if depth > 40:
        return value
    if isinstance(value, dict):
        return {
            key: _replace_strings(child, replacements, depth + 1) for key, child in value.items()
        }
    if isinstance(value, list):
        return [_replace_strings(child, replacements, depth + 1) for child in value]
    if isinstance(value, str) and value in replacements:
        return replacements[value]
    return value


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

    def _materialise_artifacts(
        self, config: dict[str, Any], artifacts: dict[str, str] | None
    ) -> dict[str, Any]:
        """Write UI-supplied rule-set bytes into the core's private data dir.

        The original (UI-side) path is used only as a lookup key.  Every file
        is stored under a content hash, so a compromised control plane cannot
        choose the destination path or overwrite an arbitrary file.
        """

        if not artifacts:
            return config
        if len(artifacts) > MAX_ARTIFACTS:
            raise EngineCheckFailed("too many configuration artifacts", "artifact_rejected")
        referenced: set[str] = set()
        _collect_path_strings(config, referenced)
        directory = self.paths.runtime_dir / "artifacts"
        replacements: dict[str, str] = {}
        total = 0
        for original, encoded in artifacts.items():
            if original not in referenced:
                raise EngineCheckFailed(
                    "configuration artifact is not referenced by the payload", "artifact_rejected"
                )
            if not isinstance(encoded, str):
                raise EngineCheckFailed(
                    "configuration artifact is not a string", "artifact_rejected"
                )
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError) as exc:
                raise EngineCheckFailed(
                    "configuration artifact is not valid base64", "artifact_rejected"
                ) from exc
            total += len(data)
            if len(data) > MAX_ARTIFACT_BYTES or total > MAX_ARTIFACTS_TOTAL_BYTES:
                raise EngineCheckFailed("configuration artifact is too large", "artifact_too_large")
            digest = hashlib.sha256(data).hexdigest()
            suffix = Path(original).suffix.lower()
            if suffix not in _ARTIFACT_SUFFIXES:
                suffix = ".bin"
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"{digest[:32]}{suffix}"
            if not target.is_file() or target.stat().st_size != len(data):
                temporary = directory / f".{digest[:32]}.tmp"
                temporary.write_bytes(data)
                if os.name == "posix":
                    temporary.chmod(0o600)
                temporary.replace(target)
            replacements[original] = str(target)
        return cast(dict[str, Any], _replace_strings(config, replacements))

    def _normalise_cache_path(self, config: dict[str, Any]) -> dict[str, Any]:
        """Point the optional sing-box cache at the core's own data directory.

        The UI may be a different user; its data directory is neither readable
        nor writable by the core.  The cache is disposable state, so the core
        owns its location regardless of what the control plane requested.
        """

        experimental = config.get("experimental")
        if not isinstance(experimental, dict):
            return config
        cache = experimental.get("cache_file")
        if not isinstance(cache, dict) or not cache.get("enabled"):
            return config
        desired = str(self.paths.data_dir / "cache.db")
        if cache.get("path") == desired:
            return config
        updated_cache = {**cache, "path": desired}
        updated_experimental = {**experimental, "cache_file": updated_cache}
        return {**config, **{"experimental": updated_experimental}}

    def _prune_artifacts(self, config: dict[str, Any]) -> None:
        directory = self.paths.runtime_dir / "artifacts"
        if not directory.is_dir():
            return
        referenced: set[str] = set()
        _collect_path_strings(config, referenced)
        keep = {Path(item).name for item in referenced}
        for item in directory.iterdir():
            if not item.is_file() or item.name in keep:
                continue
            with contextlib.suppress(OSError):
                item.unlink()

    async def start(self) -> None:
        self.paths.ensure()
        self._rotate_logs()
        # A core upgrade or crash can leave a sing-box child holding the old
        # ports.  Clean it up before any early return below; otherwise an
        # invalid or stale last-good file leaves the orphan running and the
        # next apply fails on a port conflict.
        self._cleanup_orphan()
        if not self.last_good.is_file():
            return
        if self.settings.role is Role.SERVER:
            meta = self._read_meta()
            if meta.get("policy_version") != CONFIG_POLICY_VERSION:
                # Never run a server configuration generated by an older
                # release.  It may lack newer egress blocks or quota/expiry
                # filtering.  The control plane applies a fresh configuration
                # as part of startup; until then the core stays down.
                self._last_error = (
                    "last-good configuration predates the current security policy; "
                    "waiting for the control plane to apply a new configuration"
                )
                self._write_state()
                return
        persisted_lan = self._read_persisted_allow_lan()
        try:
            raw = self.last_good.read_bytes()
            config = json.loads(raw)
            disabled = read_enforcement(self.paths.enforcement_path, strict=True)
            config, stripped = strip_disabled_users(config, disabled)
            if stripped:
                # Persist the sanitized configuration so a later core restart
                # cannot resurrect a user that the database already disabled.
                self._write_last_good(config)
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
        artifacts: dict[str, str] | None = None,
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
        async with self._lock:
            # The digest binds the bytes the control plane generated.  Any
            # normalisation below happens inside the privileged core and is
            # re-validated before it can reach sing-box.
            config = self._materialise_artifacts(config, artifacts)
            config = self._normalise_cache_path(config)
            validate_config(
                config,
                role=self.settings.role,
                allowed_ports=allowed_ports,
                allowed_paths=[self.paths.data_dir, self.paths.certs_dir],
                tun_interface=self.settings.tun_interface,
                allow_lan=allow_lan,
            )
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
                self._running_config_sha = config_digest(config)
                self._last_error = None
                self._prune_artifacts(config)
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
            # ``reload`` restarts from a file, so it must re-run the same
            # policy and path validation as ``apply``.  Trusting the file
            # would let a stale policy (or a compromised control plane) start
            # a configuration that ``apply`` would have rejected.
            try:
                config = json.loads(self.last_good.read_bytes())
            except (OSError, ValueError) as exc:
                raise EngineCheckFailed("last-good configuration is not valid JSON") from exc
            if not isinstance(config, dict):
                raise EngineCheckFailed("last-good configuration is not an object")
            if self.settings.role is Role.SERVER:
                meta = self._read_meta()
                if meta.get("policy_version") != CONFIG_POLICY_VERSION:
                    raise EngineCheckFailed(
                        "last-good configuration predates the current security policy",
                        "policy_stale",
                    )
            try:
                disabled = read_enforcement(self.paths.enforcement_path, strict=True)
            except EnforcementError as exc:
                raise EngineCheckFailed(str(exc), "enforcement_invalid") from exc
            config, stripped = strip_disabled_users(config, disabled)
            if stripped:
                self._write_last_good(config)
            validate_config(
                config,
                role=self.settings.role,
                allowed_ports=set(self.settings.proxy_ports),
                allowed_paths=[self.paths.data_dir, self.paths.certs_dir],
                tun_interface=self.settings.tun_interface,
                allow_lan=self._read_persisted_allow_lan(),
            )
            if self._process is not None and self._process.returncode is None:
                await self._reload_running()
            else:
                await self._spawn()
            self._running_config_sha = config_digest(config)
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
            # ``wait_for`` cancels the wait, not the child process.  Leaving
            # ``sing-box check`` running accumulates CPU and file descriptors
            # across failed applies and can hold the temporary config open.
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            with contextlib.suppress(Exception):
                await process.wait()
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
        if self.settings.role is Role.SERVER:
            try:
                meta = json.loads(previous_meta) if previous_meta else {}
            except (TypeError, ValueError):
                meta = {}
            if meta.get("policy_version") != CONFIG_POLICY_VERSION:
                # Never roll back into a pre-0.1.2 policy.  Keep the old bytes
                # for diagnostics but leave the core down; the control plane
                # will regenerate and retry.
                self._last_error = (
                    "rollback target predates the current security policy; "
                    "waiting for the control plane to apply a new configuration"
                )
                self._running_config_sha = None
                await self._terminate()
                self._append_log("supervisor", self._last_error)
                return
        try:
            await self._spawn()
            self._append_log("supervisor", "rollback to previous configuration")
        except Exception as exc:
            self._running_config_sha = None
            self._last_error = f"rollback failed: {exc}"
            self._append_log("supervisor", self._last_error)
            return
        try:
            self._running_config_sha = config_digest(json.loads(previous))
        except (TypeError, ValueError):
            self._running_config_sha = None

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

    def _read_meta(self) -> dict[str, Any]:
        path = self.paths.last_good_meta_path
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _read_persisted_allow_lan(self) -> bool:
        return bool(self._read_meta().get("allow_lan", False))

    def _write_last_good(self, config: dict[str, Any]) -> None:
        temporary = self.last_good.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        if os.name == "posix":
            temporary.chmod(0o600)
        temporary.replace(self.last_good)
        if os.name == "posix":
            self.last_good.chmod(0o600)

    def _write_meta(self, allow_lan: bool) -> None:
        payload = {
            "allow_lan": bool(allow_lan),
            "policy_version": CONFIG_POLICY_VERSION,
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
