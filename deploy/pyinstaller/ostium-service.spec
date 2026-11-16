# PyInstaller spec for the Windows service wrapper.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent.parent
ICON = str(ROOT / "assets" / "brand" / "ostium.ico") if sys.platform == "win32" else None
hiddenimports = (
    # uvicorn resolves its loop/protocol/lifespan implementations by string at
    # runtime.  Without collecting the submodules the Windows service exits
    # immediately with ModuleNotFoundError while the console UI (whose spec
    # already collects uvicorn) keeps working.
    collect_submodules("uvicorn")
    + collect_submodules("win32serviceutil")
    + collect_submodules("servicemanager")
)

a = Analysis(
    [str(ROOT / "deploy" / "pyinstaller" / "ostium_service.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ostium-service",
    icon=ICON,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="OstiumService")
