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


def test_generated_version_file_matches_version_file() -> None:
    assert build_info_module._packaged_version_module() is not None
    assert resolve_version() == VERSION


def test_metadata_is_used_when_generated_file_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("OSTIUM_BUILD_VERSION", raising=False)
    monkeypatch.setattr(build_info_module, "_packaged_version_module", lambda: None)
    monkeypatch.setattr(build_info_module, "_metadata_version", lambda: "1.2.3")
    assert resolve_version() == "1.2.3"
    assert version_source() == "distribution_metadata"


def test_fallback_is_explicit(monkeypatch) -> None:
    monkeypatch.delenv("OSTIUM_BUILD_VERSION", raising=False)
    monkeypatch.setattr(build_info_module, "_packaged_version_module", lambda: None)
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
