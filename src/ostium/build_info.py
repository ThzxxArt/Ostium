"""Build-time and runtime provenance for Ostium.

The control plane, the privileged core, the Web bundle and the installer must
report the same version.  Reading ``importlib.metadata`` alone cannot prove
which process owns a listening port or which Web bundle is being served, so
this module collects every source of that truth in one place.

Nothing here may import :mod:`ostium` (the package ``__init__`` imports this
module).  The generated ``_version.py`` is loaded directly from its file so a
frozen build can provide it as data without relying on ``dist-info``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any

APP_NAME = "Ostium"
FALLBACK_VERSION = "0.0.0"
_DISTRIBUTION = "ostium-ctl"


def _packaged_version_module() -> Any | None:
    """Load the generated ``_version.py`` without importing the package."""

    path = Path(__file__).with_name("_version.py")
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("ostium._generated_version", path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def _metadata_version() -> str | None:
    try:
        value = distribution(_DISTRIBUTION).version
    except PackageNotFoundError:
        return None
    value = str(value).strip()
    return value or None


def _metadata_path() -> str | None:
    try:
        value = getattr(distribution(_DISTRIBUTION), "_path", None)
    except PackageNotFoundError:
        return None
    return str(value) if value is not None else None


def resolve_version() -> str:
    """Resolve the live version in a deterministic order.

    ``OSTIUM_BUILD_VERSION`` is an explicit override used by packaging and
    tests.  The generated module wins over installed metadata because a frozen
    bundle may not carry ``dist-info`` at all; a source checkout still falls
    back to metadata when the generated file is absent or unreadable.
    """

    override = os.environ.get("OSTIUM_BUILD_VERSION", "").strip()
    if override:
        return override
    packaged = _packaged_version_module()
    if packaged is not None:
        value = str(getattr(packaged, "__version__", "") or "").strip()
        if value:
            return value
    meta = _metadata_version()
    if meta:
        return meta
    return FALLBACK_VERSION


def resolve_commit() -> str | None:
    override = os.environ.get("OSTIUM_BUILD_COMMIT", "").strip()
    if override:
        return override
    packaged = _packaged_version_module()
    if packaged is not None:
        value = str(getattr(packaged, "__commit_id__", "") or "").strip()
        if value:
            return value
    return None


def _process_started_at(pid: int) -> str | None:
    try:
        import psutil

        started = psutil.Process(pid).create_time()
    except Exception:
        return None
    from datetime import UTC, datetime

    return datetime.fromtimestamp(started, UTC).isoformat()


@dataclass(frozen=True)
class BuildInfo:
    """Every comparable fact about this process and its distribution."""

    version: str
    commit: str | None
    built_at: str | None
    frozen: bool
    executable: str
    argv: tuple[str, ...]
    pid: int
    process_started_at: str | None
    python: str
    prefix: str
    package_path: str
    dist_info_path: str | None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["argv"] = list(self.argv)
        payload["version_source"] = version_source()
        return payload


def version_source() -> str:
    if os.environ.get("OSTIUM_BUILD_VERSION", "").strip():
        return "environment"
    packaged = _packaged_version_module()
    if packaged is not None and str(getattr(packaged, "__version__", "") or "").strip():
        return "generated_version_file"
    if _metadata_version():
        return "distribution_metadata"
    return "fallback"


def build_info() -> BuildInfo:
    built_at = os.environ.get("OSTIUM_BUILD_TIME", "").strip() or None
    return BuildInfo(
        version=resolve_version(),
        commit=resolve_commit(),
        built_at=built_at,
        frozen=bool(getattr(sys, "frozen", False)),
        executable=sys.executable or "",
        argv=tuple(sys.argv),
        pid=os.getpid(),
        process_started_at=_process_started_at(os.getpid()),
        python=sys.version.split()[0],
        prefix=sys.prefix,
        package_path=str(Path(__file__).resolve().parent),
        dist_info_path=_metadata_path(),
    )


def read_web_build(dist: Path | None) -> dict[str, Any]:
    """Read the build manifest emitted next to the SPA entry point."""

    if dist is None:
        return {"available": False, "reason": "web bundle is not installed"}
    path = dist / "build.json"
    if not path.is_file():
        return {"available": False, "path": str(path), "reason": "build.json is missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"available": False, "path": str(path), "reason": f"unreadable: {exc}"}
    if not isinstance(payload, dict):
        return {"available": False, "path": str(path), "reason": "build.json is not an object"}
    return {"available": True, "path": str(path), **payload}


def listener_info(port: int, *, host: str | None = None) -> dict[str, Any]:
    """Return the process that actually owns a listening port."""

    result: dict[str, Any] = {
        "port": port,
        "host": host,
        "found": False,
        "pid": None,
        "exe": None,
        "name": None,
        "cmdline": None,
        "started_at": None,
    }
    try:
        import psutil

        connections = psutil.net_connections(kind="inet")
    except Exception as exc:
        result["error"] = str(exc)
        return result
    candidates = [
        connection
        for connection in connections
        if connection.status == psutil.CONN_LISTEN
        and connection.laddr is not None
        and int(connection.laddr.port) == int(port)
    ]
    if not candidates:
        return result
    connection = next((item for item in candidates if item.pid), candidates[0])
    result["found"] = True
    if connection.pid is None:
        return result
    result["pid"] = int(connection.pid)
    try:
        process = psutil.Process(connection.pid)
        result["exe"] = process.exe()
        result["name"] = process.name()
        result["cmdline"] = process.cmdline()
        result["started_at"] = _process_started_at(connection.pid)
    except Exception as exc:
        result["error"] = str(exc)
    return result


def version_mismatches(
    expected: str,
    *,
    core: str | None = None,
    web: str | None = None,
) -> list[dict[str, Any]]:
    """Compare the version surfaces an operator can actually observe."""

    mismatches: list[dict[str, Any]] = []
    for surface, value in (("core", core), ("web", web)):
        if value is None:
            continue
        if str(value).strip() != expected:
            mismatches.append({"surface": surface, "expected": expected, "actual": str(value)})
    return mismatches
