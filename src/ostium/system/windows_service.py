"""Windows Service wrapper for ``ostium core-run`` (client TUN core).

This module is imported only on Windows.  The service is installed by the
Inno Setup installer via ``ostium-service --startup auto install``.
"""

from __future__ import annotations

import sys

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
