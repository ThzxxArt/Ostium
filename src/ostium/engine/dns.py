"""Data-plane DNS policy and DoH probing."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from constance import config as runtime_config

logger = logging.getLogger("ostium.engine.dns")


class DNSError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DNSPlan:
    servers: list[dict]
    final: str
    effective_mode: str
    warning: str = ""


def _doh_server(url: str) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise DNSError("DoH URL must be an https:// URL with a host.")
    if parsed.username or parsed.password:
        raise DNSError("DoH URL must not contain credentials.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise DNSError("DoH URL contains an invalid port.") from exc
    server: dict = {
        "type": "https",
        "tag": "remote",
        "server": parsed.hostname,
        "path": parsed.path or "/dns-query",
    }
    if port and port != 443:
        server["server_port"] = port
    return server


def _dns_probe_query() -> bytes:
    """Build a minimal DNS A query for the RFC 8484 GET probe."""

    import secrets
    import struct

    labels = b"\x07example\x03com\x00"
    header = struct.pack(">HHHHHH", secrets.randbits(16), 0x0100, 1, 0, 0, 0)
    return header + labels + struct.pack(">HH", 1, 1)


def doh_available(url: str, *, timeout: float = 3.0) -> bool:
    import base64

    query = base64.urlsafe_b64encode(_dns_probe_query()).rstrip(b"=").decode("ascii")
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.get(
                url,
                params={"dns": query},
                headers={"accept": "application/dns-message"},
            )
            return response.status_code == 200 and len(response.content) >= 12
    except httpx.HTTPError as exc:
        logger.info("DoH probe failed: %s", exc)
        return False


def build_dns_plan(*, mode: str | None = None, url: str | None = None, probe: bool = True) -> DNSPlan:
    mode = (mode or runtime_config.server_dns_mode or "auto").lower()
    url = url or runtime_config.server_dns_doh_url
    local = {"type": "udp", "tag": "local", "server": "1.1.1.1"}

    if mode not in {"auto", "doh", "udp"}:
        raise DNSError(f"Unknown DNS mode: {mode}")

    if mode == "udp":
        return DNSPlan([local], "local", "udp")

    remote = _doh_server(url)
    if mode == "doh":
        if probe and not doh_available(url):
            raise DNSError("DoH is required but the endpoint is not reachable.")
        return DNSPlan([remote, local], "remote", "doh")

    if probe and not doh_available(url):
        return DNSPlan(
            [local],
            "local",
            "udp",
            warning="DoH probe failed; the data plane fell back to UDP DNS.",
        )
    return DNSPlan([remote, local], "remote", "doh")


__all__ = ["DNSError", "DNSPlan", "build_dns_plan", "doh_available"]
