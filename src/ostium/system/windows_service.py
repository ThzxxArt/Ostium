"""Windows Service wrapper for ``ostium core-run`` (client TUN core).

This module is imported only on Windows.  The service is installed by the
Inno Setup installer via ``ostium-service --startup auto install``.
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path


def service_paths(
    *,
    program_data: Path | None = None,
    install_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Return the machine-wide (data dir, core config) used by the service.

    The service executable lives in ``<install_dir>/service``.  Keeping its
    configuration next to the admin-only executable prevents a local user from
    pointing ``engine_path`` at a binary that LocalSystem would execute.
    """

    data_root = program_data or Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    # The privileged core keeps its token, last-good config and database in a
    # separate directory whose ACL grants write access only to SYSTEM and
    # Administrators.  The user-writable UI data directory is ``Ostium``.
    data_dir = data_root / "OstiumCore"
    if install_dir is None:
        if getattr(sys, "frozen", False):
            install_dir = Path(sys.executable).resolve().parent.parent
        else:
            install_dir = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Ostium"
    return data_dir, install_dir / "service" / "core.toml"


def service_log_path() -> Path:
    """Machine-wide service log used before the event log is available."""

    data_dir, _ = service_paths()
    return data_dir / "logs" / "service.log"


def _service_log(message: str) -> None:
    try:
        path = service_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now(UTC).isoformat()} {message}\n")
    except Exception:
        # Logging must never mask the original service startup failure.
        pass


if sys.platform != "win32":  # pragma: no cover - import guard

    def main() -> None:
        raise SystemExit("Windows services are only available on Windows")

else:  # pragma: no cover - exercised on Windows
    import threading

    import servicemanager
    import uvicorn
    import win32event
    import win32service
    import win32serviceutil

    from ostium.config import Settings
    from ostium.core.app import create_core_app

    class OstiumCoreService(win32serviceutil.ServiceFramework):
        _svc_name_ = "OstiumCore"
        _svc_display_name_ = "Ostium Proxy Core"
        _svc_description_ = "Privileged sing-box supervisor for Ostium TUN mode."

        def __init__(self, args: list[str]) -> None:
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.server: uvicorn.Server | None = None
            self.thread: threading.Thread | None = None

        def SvcStop(self) -> None:
            _service_log("stop requested")
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)
            if self.server is not None:
                self.server.should_exit = True

        def SvcDoRun(self) -> None:
            stream = None
            original_stdout, original_stderr = sys.stdout, sys.stderr
            try:
                log_path = service_log_path()
                log_path.parent.mkdir(parents=True, exist_ok=True)
                # A service has no console.  Redirect uvicorn and root logger
                # output to service.log so an early exit leaves a diagnosable
                # trace instead of only a generic SCM error.
                stream = log_path.open("a", encoding="utf-8", buffering=1)
                sys.stdout = stream
                sys.stderr = stream
                servicemanager.LogInfoMsg("Ostium core service starting")
                _service_log(f"starting executable={sys.executable}")
                # Windows services run as LocalSystem and do not inherit the
                # installer's environment.  Force the machine-wide layout instead
                # of accepting a potentially user-controlled inherited value.
                data_dir, config_file = service_paths()
                _service_log(f"data_dir={data_dir} config_file={config_file}")
                os.environ["OSTIUM_ROLE"] = "client"
                os.environ["OSTIUM_DATA_DIR"] = str(data_dir)
                os.environ["OSTIUM_CONFIG_FILE"] = str(config_file)
                # The service manager starts us in System32.  Never let sing-box
                # resolve relative files (cache.db, rule sets) against a protected
                # system directory.
                os.chdir(data_dir)
                settings = Settings.load()
                _service_log(
                    f"settings loaded role={settings.role.value} engine={settings.engine_path}"
                )
                app = create_core_app(settings)
                _service_log("core app created")
                config = uvicorn.Config(
                    app,
                    host="127.0.0.1",
                    port=8788,
                    log_level=settings.log_level,
                    access_log=False,
                    server_header=False,
                    # The core API has no WebSocket routes.  Keep the service
                    # independent of optional websocket implementations.
                    ws="none",
                )
                self.server = uvicorn.Server(config)
                self.server.run()
                _service_log("uvicorn stopped")
                servicemanager.LogInfoMsg("Ostium core service stopped")
            except BaseException:
                _service_log("service failed:\n" + traceback.format_exc())
                try:
                    servicemanager.LogErrorMsg(
                        "Ostium core service failed; see "
                        r"%ProgramData%\OstiumCore\logs\service.log"
                    )
                except Exception:
                    pass
                raise
            finally:
                sys.stdout, sys.stderr = original_stdout, original_stderr
                if stream is not None:
                    try:
                        stream.flush()
                        stream.close()
                    except OSError:
                        pass

    def main() -> None:
        win32serviceutil.HandleCommandLine(OstiumCoreService)
