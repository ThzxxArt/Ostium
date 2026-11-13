"""SSRF guards for server-side outbound requests."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

METADATA_ADDRESSES = {
    "169.254.169.254",
    "169.254.170.2",
    "169.254.170.23",
    "100.100.100.200",
    "fd00:ec2::254",
}


class UnsafeUrlError(ValueError):
    """The URL points at an address that must never be fetched server-side."""


def _is_blocked(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_private: bool
) -> bool:
    if str(address) in METADATA_ADDRESSES:
        return True
    if address.is_loopback or address.is_link_local or address.is_multicast:
        return True
    if address.is_unspecified or address.is_reserved:
        return True
    return bool(not allow_private and address.is_private)


def validate_remote_url(url: str, *, allow_private: bool = False) -> str:
    """Validate an outbound http(s) URL and its resolved addresses.

    ``allow_private`` is used for client subscriptions, which legitimately
    point at a LAN server.  Loopback, link-local and cloud metadata remain
    blocked in every case.
    """

    value = url.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrlError("URL must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URL must not embed credentials")
    host = parsed.hostname.strip("[]")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_blocked(literal, allow_private):
            raise UnsafeUrlError(f"URL address {host} is not allowed")
        return value
    if host.lower() in {"localhost", "localhost.localdomain"} or host.lower().endswith(".local"):
        raise UnsafeUrlError("local hostnames are not allowed")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"could not resolve {host}: {exc}") from exc
    addresses = {str(info[4][0]) for info in infos}
    if not addresses:
        raise UnsafeUrlError(f"could not resolve {host}")
    for raw in addresses:
        try:
            address = ipaddress.ip_address(raw.split("%", 1)[0])
        except ValueError:
            continue
        if _is_blocked(address, allow_private):
            raise UnsafeUrlError(f"URL resolves to a blocked address: {raw}")
    return value
