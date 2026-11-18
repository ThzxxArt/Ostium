"""Supervision of the pinned sing-box child process."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import psutil
from django.conf import settings

from ostium import paths
from ostium.engine.runtime import tail_file

logger = logging.getLogger("ostium.engine.supervisor")


class SupervisorError(RuntimeError):
    pass


def binary_path() -> Path:
    return Path(settings.OSTIUM_SINGBOX_PATH).resolve()


def verify_binary() -> tuple[bool, str]:
    binary = binary_path()
    if not binary.is_file():
        return False, f"sing-box binary not found at {binary}"
    if not os.access(binary, os.X_OK):
        return False, f"sing-box binary is not executable: {binary}"
    expected = settings.OSTIUM_SINGBOX_BINARY_SHA256.strip().lower()
    if expected:
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        if digest != expected:
            return False, "sing-box binary SHA256 does not match OSTIUM_SINGBOX_BINARY_SHA256"
    try:
        proc = subprocess.run([str(binary), "version"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"cannot execute sing-box: {exc}"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()[:500]
    return True, (proc.stdout or "").splitlines()[0] if proc.stdout else "sing-box"


def binary_version() -> str:
    ok, message = verify_binary()
    if not ok:
        return message
    return message.removeprefix("sing-box version ").strip()


class Supervisor:
    def __init__(
        self,
        *,
        binary: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        self.binary = binary or binary_path()
        self.log_path = log_path or paths.singbox_log_path()
        self.process: subprocess.Popen[bytes] | None = None
        self._log_handle = None

    @property
    def pid(self) -> int | None:
        if self.process is None:
            return None
        return self.process.pid if self.process.poll() is None else None

    @property
    def running(self) -> bool:
        return self.pid is not None and psutil.pid_exists(self.pid)

    def start(self, config_path: Path) -> int:
        if self.running:
            raise SupervisorError("sing-box is already running.")
        paths.ensure()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = self.log_path.open("ab")
        try:
            self.process = subprocess.Popen(
                [str(self.binary), "run", "-c", str(config_path)],
                stdin=subprocess.DEVNULL,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            self._close_log()
            raise SupervisorError(f"Could not start sing-box: {exc}") from exc

        time.sleep(0.75)
        if self.process.poll() is not None:
            code = self.process.returncode
            self._close_log()
            tail = tail_file(self.log_path, max_bytes=8000)
            raise SupervisorError(f"sing-box exited during startup with code {code}: {tail[-2000:]}")
        logger.info("sing-box started pid=%s config=%s", self.process.pid, config_path)
        return self.process.pid

    def stop(self, timeout: float = 10.0) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except ProcessLookupError, PermissionError:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                time.sleep(0.1)
            if process.poll() is None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except ProcessLookupError, PermissionError:
                    process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        self.process = None
        self._close_log()
        logger.info("sing-box stopped")

    def restart(self, config_path: Path) -> int:
        self.stop()
        return self.start(config_path)

    def _close_log(self) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None

    def __enter__(self) -> Supervisor:
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()


def terminate_orphans(*, keep_pid: int | None = None) -> list[int]:
    """Terminate sing-box processes left behind by a previous worker."""

    killed: list[int] = []
    target = str(binary_path())
    runtime = paths.runtime_dir().resolve()

    def config_path_from(cmdline: list[str]) -> Path | None:
        for index, token in enumerate(cmdline):
            if token in {"-c", "--config"} and index + 1 < len(cmdline):
                return Path(cmdline[index + 1])
            if token.startswith("--config="):
                return Path(token.split("=", 1)[1])
        return None

    for proc in psutil.process_iter(["pid", "name", "cmdline", "exe"]):
        try:
            if keep_pid is not None and proc.pid == keep_pid:
                continue
            cmdline = proc.info.get("cmdline") or []
            exe = proc.info.get("exe") or ""
            if not cmdline:
                continue
            is_singbox = os.path.basename(cmdline[0]) == "sing-box" or exe == target
            if not is_singbox or "run" not in cmdline:
                continue
            # Only terminate processes running a config from *our* runtime
            # directory. Client instances and concurrent checks survive.
            config_path = config_path_from(cmdline)
            if config_path is None:
                continue
            if config_path.resolve().parent != runtime:
                continue
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                proc.kill()
            killed.append(proc.pid)
        except psutil.NoSuchProcess, psutil.AccessDenied:
            continue
    return killed


def disk_free_bytes() -> int:
    usage = shutil.disk_usage(paths.data_dir())
    return usage.free
