"""Ostium package metadata and public constants."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ostium-art")
except PackageNotFoundError:  # pragma: no cover - source checkout without install
    __version__ = "0.1.0"

APP_NAME = "Ostium"
API_PREFIX = "/api/v1"
CORE_API_VERSION = "v1"
PROFILE_FORMAT_VERSION = 1
USER_AGENT = f"Ostium/{__version__}"

__all__ = [
    "API_PREFIX",
    "APP_NAME",
    "CORE_API_VERSION",
    "PROFILE_FORMAT_VERSION",
    "USER_AGENT",
    "__version__",
]
