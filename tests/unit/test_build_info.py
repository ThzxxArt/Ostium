"""Build and runtime provenance must be deterministic and testable."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from ostium.build_info import (
    BuildInfo,
    build_info,
    listener_info,
    read_web_build,
    resolve_commit,
    resolve_version,
    version_mismatches,
    version_source,
)

build_info_module = importlib.import_module("ostium.build_info")

ROOT = Path(__file__).resolve().parents[2]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_environment_override_wins(monkeypatch) -> None:
    monkeypatch.setenv("OSTIUM_BUILD_VERSION", "9.9.9")
    assert resolve_version() == "9.9.9"
    assert version_source() == "environment"


def test_source_checkout_prefers_version_file_over_generated(monkeypatch) -> None:
    class Packaged:
        __version__ = "9.9.9"

    monkeypatch.delenv("OSTIUM_BUILD_VERSION", raising=False)
    monkeypatch.setattr(build_info_module, "_packaged_version_module", lambda: Packaged())
    monkeypatch.setattr(build_info_module, "_version_file_version", lambda: "0.1.12")
    monkeypatch.setattr(build_info_module.sys, "frozen", False, raising=False)
    assert resolve_version() == "0.1.12"
    assert version_source() == "version_file"


def test_generated_version_file_matches_version_file() -> None:
    assert resolve_version() == VERSION


def test_metadata_is_used_when_generated_file_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("OSTIUM_BUILD_VERSION", raising=False)
    monkeypatch.setattr(build_info_module, "_packaged_version_module", lambda: None)
    monkeypatch.setattr(build_info_module, "_version_file_version", lambda: None)
    monkeypatch.setattr(build_info_module, "_metadata_version", lambda: "1.2.3")
    assert resolve_version() == "1.2.3"
    assert version_source() == "distribution_metadata"


def test_fallback_is_explicit(monkeypatch) -> None:
    monkeypatch.delenv("OSTIUM_BUILD_VERSION", raising=False)
    monkeypatch.setattr(build_info_module, "_packaged_version_module", lambda: None)
    monkeypatch.setattr(build_info_module, "_version_file_version", lambda: None)
    monkeypatch.setattr(build_info_module, "_metadata_version", lambda: None)
    assert resolve_version() == build_info_module.FALLBACK_VERSION
    assert version_source() == "fallback"


def test_commit_override_and_absence(monkeypatch) -> None:
    monkeypatch.setenv("OSTIUM_BUILD_COMMIT", "abc123")
    assert resolve_commit() == "abc123"
    monkeypatch.delenv("OSTIUM_BUILD_COMMIT")
    monkeypatch.setattr(
        build_info_module,
        "_packaged_version_module",
        lambda: type("Module", (), {"__commit_id__": None})(),
    )
    assert resolve_commit() is None


def test_build_info_payload_is_json_serialisable() -> None:
    info = build_info()
    assert isinstance(info, BuildInfo)
    payload = info.as_dict()
    assert payload["version"] == resolve_version()
    assert payload["pid"] > 0
    assert isinstance(payload["argv"], list)
    assert payload["version_source"] in {
        "environment",
        "generated_version_file",
        "version_file",
        "distribution_metadata",
        "fallback",
    }
    json.dumps(payload)


def test_read_web_build_reports_missing_and_present(tmp_path: Path) -> None:
    missing = read_web_build(tmp_path)
    assert missing["available"] is False

    (tmp_path / "build.json").write_text(
        json.dumps({"version": "1.2.3", "commit": "abc", "digest": "d"}), encoding="utf-8"
    )
    present = read_web_build(tmp_path)
    assert present["available"] is True
    assert present["version"] == "1.2.3"


def test_listener_info_for_unused_port() -> None:
    # Port 1 has no listener in unprivileged test environments.
    result = listener_info(1)
    assert result["found"] is False
    assert result["pid"] is None


def test_version_mismatches_skip_unknown_surfaces() -> None:
    assert version_mismatches("1.0.0") == []
    assert version_mismatches("1.0.0", core="1.0.0", web="1.0.0") == []
    mismatches = version_mismatches("1.0.0", core="0.9.0")
    assert mismatches == [{"surface": "core", "expected": "1.0.0", "actual": "0.9.0"}]


class _MissingPath:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def resolve(self):  # type: ignore[no-untyped-def]
        return self

    @property
    def parent(self):  # type: ignore[no-untyped-def]
        return self

    def with_name(self, name: str):  # type: ignore[no-untyped-def]
        return self

    def __truediv__(self, other: str):  # type: ignore[no-untyped-def]
        return self

    def is_file(self) -> bool:
        return False


def test_packaged_module_missing_and_broken(monkeypatch) -> None:
    monkeypatch.setattr(build_info_module, "Path", _MissingPath)
    assert build_info_module._packaged_version_module() is None

    class _Present(_MissingPath):
        def is_file(self) -> bool:
            return True

    monkeypatch.setattr(build_info_module, "Path", _Present)
    monkeypatch.setattr(
        build_info_module.importlib.util, "spec_from_file_location", lambda *a: None
    )
    assert build_info_module._packaged_version_module() is None

    class _Spec:
        loader = object()

        @staticmethod
        def exec_module(module) -> None:  # type: ignore[no-untyped-def]
            raise RuntimeError("broken")

    class _RealSpec:
        loader = _Spec()

    monkeypatch.setattr(
        build_info_module.importlib.util,
        "spec_from_file_location",
        lambda *a: _RealSpec(),
    )
    assert build_info_module._packaged_version_module() is None


def test_metadata_helpers_handle_missing_distribution(monkeypatch) -> None:
    def missing(name: str):  # type: ignore[no-untyped-def]
        raise build_info_module.PackageNotFoundError(name)

    monkeypatch.setattr(build_info_module, "distribution", missing)
    assert build_info_module._metadata_version() is None
    assert build_info_module._metadata_path() is None


def test_metadata_helpers_handle_empty_and_missing_path(monkeypatch) -> None:
    class Dist:
        version = "  "
        _path = None

    monkeypatch.setattr(build_info_module, "distribution", lambda name: Dist())
    assert build_info_module._metadata_version() is None
    assert build_info_module._metadata_path() is None

    class DistPath:
        version = "1.0.0"
        _path = "/tmp/dist-info"

    monkeypatch.setattr(build_info_module, "distribution", lambda name: DistPath())
    assert build_info_module._metadata_version() == "1.0.0"
    assert build_info_module._metadata_path() == "/tmp/dist-info"


def test_version_file_missing_and_unreadable(monkeypatch) -> None:
    monkeypatch.setattr(build_info_module, "Path", _MissingPath)
    assert build_info_module._version_file_version() is None

    class _Unreadable(_MissingPath):
        def is_file(self) -> bool:
            return True

        def read_text(self, encoding: str = "utf-8") -> str:
            raise OSError("denied")

    monkeypatch.setattr(build_info_module, "Path", _Unreadable)
    assert build_info_module._version_file_version() is None

    class _Empty(_Unreadable):
        def read_text(self, encoding: str = "utf-8") -> str:
            return "  \n"

    monkeypatch.setattr(build_info_module, "Path", _Empty)
    assert build_info_module._version_file_version() is None


def test_resolve_version_frozen_and_suffixed_fallbacks(monkeypatch) -> None:
    class Packaged:
        __version__ = "1.2.3.dev4"

    monkeypatch.delenv("OSTIUM_BUILD_VERSION", raising=False)
    monkeypatch.setattr(build_info_module, "_packaged_version_module", lambda: Packaged())
    monkeypatch.setattr(build_info_module, "_version_file_version", lambda: None)
    monkeypatch.setattr(build_info_module, "_metadata_version", lambda: "1.2.3")
    assert resolve_version() == "1.2.3"

    monkeypatch.setattr(build_info_module, "_metadata_version", lambda: None)
    assert resolve_version() == "1.2.3.dev4"
    assert version_source() == "generated_version_file"

    monkeypatch.setattr(build_info_module, "_packaged_version_module", lambda: None)
    assert resolve_version() == build_info_module.FALLBACK_VERSION
    assert version_source() == "fallback"


def test_resolve_version_uses_metadata_when_frozen(monkeypatch) -> None:
    monkeypatch.delenv("OSTIUM_BUILD_VERSION", raising=False)
    monkeypatch.setattr(build_info_module, "_packaged_version_module", lambda: None)
    monkeypatch.setattr(build_info_module, "_version_file_version", lambda: VERSION)
    monkeypatch.setattr(build_info_module, "_metadata_version", lambda: "9.9.9")
    monkeypatch.setattr(build_info_module.sys, "frozen", True, raising=False)
    assert resolve_version() == "9.9.9"
    assert version_source() == "distribution_metadata"


def test_commit_from_packaged_module(monkeypatch) -> None:
    class Packaged:
        __commit_id__ = "deadbeef"

    monkeypatch.delenv("OSTIUM_BUILD_COMMIT", raising=False)
    monkeypatch.setattr(build_info_module, "_packaged_version_module", lambda: Packaged())
    assert resolve_commit() == "deadbeef"


def test_process_start_failure(monkeypatch) -> None:
    def fail(pid: int):  # type: ignore[no-untyped-def]
        raise RuntimeError("gone")

    monkeypatch.setattr("psutil.Process", fail)
    assert build_info_module._process_started_at(123) is None


def test_build_info_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv("OSTIUM_BUILD_TIME", "2026-11-17T00:00:00+00:00")
    payload = build_info().as_dict()
    assert payload["built_at"] == "2026-11-17T00:00:00+00:00"


def test_read_web_build_invalid_payloads(tmp_path: Path) -> None:
    assert read_web_build(None)["available"] is False

    (tmp_path / "build.json").write_text("{not-json", encoding="utf-8")
    assert read_web_build(tmp_path)["available"] is False

    (tmp_path / "build.json").write_text("[]", encoding="utf-8")
    result = read_web_build(tmp_path)
    assert result["available"] is False
    assert "not an object" in result["reason"]


def test_listener_info_success_and_failures(monkeypatch) -> None:
    from types import SimpleNamespace

    import psutil

    connection = SimpleNamespace(
        status=psutil.CONN_LISTEN,
        laddr=SimpleNamespace(port=12345),
        pid=4321,
    )
    monkeypatch.setattr(psutil, "net_connections", lambda kind: [connection])

    class Process:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def exe(self) -> str:
            return "/usr/bin/ostium"

        def name(self) -> str:
            return "ostium"

        def cmdline(self) -> list[str]:
            return ["ostium", "serve"]

        def create_time(self) -> float:
            return 0

    monkeypatch.setattr(psutil, "Process", Process)
    result = listener_info(12345, host="127.0.0.1")
    assert result["found"] is True
    assert result["pid"] == 4321
    assert result["exe"] == "/usr/bin/ostium"
    assert result["started_at"]

    connection.pid = None
    result = listener_info(12345)
    assert result["found"] is True
    assert result["pid"] is None

    def fail(kind: str):  # type: ignore[no-untyped-def]
        raise RuntimeError("no net")

    monkeypatch.setattr(psutil, "net_connections", fail)
    result = listener_info(12345)
    assert result["found"] is False
    assert "no net" in result["error"]
