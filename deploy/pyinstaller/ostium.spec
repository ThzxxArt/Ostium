# PyInstaller spec for the Ostium console (Windows/macOS/Linux).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent.parent
ICON = str(ROOT / "assets" / "brand" / "ostium.ico") if sys.platform == "win32" else None
datas = [
    (str(ROOT / "web" / "dist"), "ostium/web/dist"),
    (str(ROOT / "alembic"), "ostium/db/alembic"),
]
hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("websockets")
    + collect_submodules("grpc")
    + collect_submodules("acme")
    + collect_submodules("josepy")
)

a = Analysis(
    [str(ROOT / "src" / "ostium" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ostium",
    icon=ICON,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Ostium")
