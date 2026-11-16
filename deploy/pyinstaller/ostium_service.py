"""PyInstaller entry point for the Windows service executable."""

from __future__ import annotations

import os
import traceback
from datetime import UTC, datetime
from pathlib import Path


def _bootstrap_log(message: str) -> None:
    """Record failures that happen before the service log is available."""

    try:
        root = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "OstiumCore" / "logs"
        root.mkdir(parents=True, exist_ok=True)
        with (root / "service-bootstrap.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now(UTC).isoformat()} {message}\n")
    except Exception:
        pass


try:
    from ostium.system.windows_service import main
except BaseException:
    _bootstrap_log("import failed:\n" + traceback.format_exc())
    raise

if __name__ == "__main__":
    try:
        main()
    except Exception:
        _bootstrap_log("main failed:\n" + traceback.format_exc())
        raise
