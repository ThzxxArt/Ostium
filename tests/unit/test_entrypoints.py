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


def test_windows_service_paths_are_machine_scoped(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from ostium.system.windows_service import service_paths

    data_dir, config_file = service_paths(
        program_data=tmp_path / "ProgramData",
        install_dir=tmp_path / "Program Files" / "Ostium",
    )
    assert data_dir == tmp_path / "ProgramData" / "OstiumCore"
    assert config_file == tmp_path / "Program Files" / "Ostium" / "service" / "core.toml"


def test_windows_service_paths_from_environment_and_frozen_executable(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    import sys

    from ostium.system.windows_service import service_paths

    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path / "Program Files"))
    monkeypatch.delattr(sys, "frozen", raising=False)
    data_dir, config_file = service_paths()
    assert data_dir == tmp_path / "ProgramData" / "OstiumCore"
    assert config_file == tmp_path / "Program Files" / "Ostium" / "service" / "core.toml"

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        sys,
        "executable",
        str(tmp_path / "Program Files" / "Ostium" / "service" / "ostium-service.exe"),
    )
    data_dir, config_file = service_paths()
    assert data_dir == tmp_path / "ProgramData" / "OstiumCore"
    assert config_file == tmp_path / "Program Files" / "Ostium" / "service" / "core.toml"


def test_windows_service_log_is_best_effort(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ostium.system import windows_service

    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    path = windows_service.service_log_path()
    assert path == tmp_path / "ProgramData" / "OstiumCore" / "logs" / "service.log"
    windows_service._service_log("hello")
    assert "hello" in path.read_text(encoding="utf-8")

    def broken() -> None:
        raise OSError("log unavailable")

    monkeypatch.setattr(windows_service, "service_log_path", broken)
    windows_service._service_log("ignored")


def test_runpy_main(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["ostium", "version"])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("ostium", run_name="__main__")
    assert excinfo.value.code == 0
