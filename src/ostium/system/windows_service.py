"""Windows Service wrapper for ``ostium core-run`` (client TUN core).

This module is imported only on Windows.  The service is installed by the
Inno Setup installer via ``ostium-service --startup auto install``.
"""

from __future__ import annotations

import os
import sys
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
    data_dir = data_root / "Ostium"
    if install_dir is None:
        if getattr(sys, "frozen", False):
            install_dir = Path(sys.executable).resolve().parent.parent
        else:
            install_dir = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Ostium"
    return data_dir, install_dir / "service" / "core.toml"


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
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)
            if self.server is not None:
                self.server.should_exit = True

        def SvcDoRun(self) -> None:
            servicemanager.LogInfoMsg("Ostium core service starting")
            # Windows services run as LocalSystem and do not inherit the
            # installer's environment.  Force the machine-wide layout instead
            # of accepting a potentially user-controlled inherited value.
            data_dir, config_file = service_paths()
            os.environ["OSTIUM_ROLE"] = "client"
            os.environ["OSTIUM_DATA_DIR"] = str(data_dir)
            os.environ["OSTIUM_CONFIG_FILE"] = str(config_file)
            settings = Settings.load()
            app = create_core_app(settings)
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=8788,
                log_level=settings.log_level,
                access_log=False,
                server_header=False,
            )
            self.server = uvicorn.Server(config)
            self.server.run()
            servicemanager.LogInfoMsg("Ostium core service stopped")

    def main() -> None:
        win32serviceutil.HandleCommandLine(OstiumCoreService)
