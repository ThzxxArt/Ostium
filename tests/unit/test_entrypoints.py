from __future__ import annotations

import importlib
import runpy

import pytest


def test_package_entrypoint() -> None:
    module = importlib.import_module("ostium.__main__")
    assert module is not None
    with pytest.raises(SystemExit):
        module.app()


def test_windows_service_guard() -> None:
    module = importlib.import_module("ostium.system.windows_service")
    with pytest.raises(SystemExit, match="Windows services"):
        module.main()


def test_runpy_main(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["ostium", "version"])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("ostium", run_name="__main__")
    assert excinfo.value.code == 0
