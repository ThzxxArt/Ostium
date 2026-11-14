"""SSRF guards for server-side outbound requests."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

METADATA_ADDRESSES = {
    "169.254.169.254",
    "169.254.170.2",
    "169.254.170.23",
    "100.100.100.200",
    "fd00:ec2::254",
}
CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


class UnsafeUrlError(ValueError):
    """The URL points at an address that must never be fetched server-side."""


def validate_target_host(host: str, *, allow_private: bool = False) -> str:
    """Reject obviously unsafe destinations without a DNS lookup.

    Literal loopback/private/metadata addresses and local hostnames can never
    be legitimate public targets.  Hostnames are left to the resolver because
    callers such as the Reality preflight only need to block direct pivots.
    """

    value = host.strip().strip("[]").lower()
    if not value:
        raise UnsafeUrlError("host is empty")
    try:
        literal = ipaddress.ip_address(value)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_blocked(literal, allow_private):
            raise UnsafeUrlError(f"host address {host} is not allowed")
        return value
    if value in {"localhost", "localhost.localdomain"} or value.endswith(".local"):
        raise UnsafeUrlError("local hostnames are not allowed")
    return value


def _is_blocked(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_private: bool
) -> bool:
    normalized = _normalise_address(address)
    if normalized is None:
        # Teredo tunnels can carry an embedded IPv4 address that is not
        # visible to the checks below; they are never a legitimate target.
        return True
    if str(normalized) in METADATA_ADDRESSES:
        return True
    if (
        normalized.is_loopback
        or normalized.is_link_local
        or normalized.is_multicast
        or normalized.is_unspecified
        or normalized.is_reserved
    ):
        return True
    # Python's ``is_private`` does not classify 100.64.0.0/10 as private.
    # Treat it as private for outbound policy (server egress already blocks it).
    if not allow_private and normalized in CGNAT_NETWORK:
        return True
    return bool(not allow_private and normalized.is_private)


def _normalise_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Unwrap IPv4-in-IPv6 forms before applying the address policy.

    ``::ffff:100.100.100.200`` and ``2002:6464:64c8::1`` both reach the
    Alibaba metadata address over an IPv6 socket, but neither string matches
    the IPv4 metadata literal.  Normalise them so the same policy applies.
    """

    if not isinstance(address, ipaddress.IPv6Address):
        return address
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address.sixtofour is not None:
        return address.sixtofour
    if address.teredo is not None:
        return None
    return address


def validate_remote_url(url: str, *, allow_private: bool = False) -> str:
    """Validate an outbound http(s) URL and its resolved addresses.

    ``allow_private`` is used for client subscriptions, which legitimately
    point at a LAN server.  Loopback, link-local and cloud metadata remain
    blocked in every case.
    """

    value = url.strip()
    try:
        parsed = urlparse(value)
    except ValueError as exc:
        raise UnsafeUrlError(f"invalid URL: {exc}") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrlError("URL must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URL must not embed credentials")
    host = parsed.hostname.strip("[]")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeUrlError(f"invalid port in URL: {exc}") from exc
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


MAX_REDIRECTS = 5


@dataclass(frozen=True)
class FetchedPayload:
    """A bounded HTTP GET result with every redirect hop re-validated."""

    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes

    @property
    def text(self) -> str:
        charset = "utf-8"
        content_type = self.headers.get("content-type", "")
        for part in content_type.split(";")[1:]:
            key, _, value = part.strip().partition("=")
            if key.lower() == "charset" and value:
                charset = value.strip("\"'")
                break
        try:
            return self.content.decode(charset, errors="replace")
        except LookupError:
            # A malicious or broken server must not turn an unknown charset
            # into an unhandled 500 in the subscription/rule-set importer.
            return self.content.decode("utf-8", errors="replace")


async def fetch_limited(
    url: str,
    *,
    allow_private: bool = False,
    max_bytes: int,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
) -> FetchedPayload:
    """GET a URL while enforcing SSRF policy on the initial URL and redirects.

    ``httpx`` follows redirects internally without re-running the DNS/address
    policy, so a public URL could redirect to cloud metadata.  This helper
    disables automatic redirects, validates every ``Location`` and streams the
    body through a hard byte limit.
    """

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    current = validate_remote_url(url, allow_private=allow_private)
    require_https = urlparse(current).scheme.lower() == "https"
    for _hop in range(MAX_REDIRECTS + 1):
        async with (
            httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=min(5.0, timeout)),
                follow_redirects=False,
                trust_env=False,
            ) as client,
            client.stream("GET", current, headers=headers) as response,
        ):
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location", "")
                if not location:
                    raise UnsafeUrlError("redirect response did not include a Location")
                target = validate_remote_url(
                    urljoin(current, location), allow_private=allow_private
                )
                if require_https and urlparse(target).scheme.lower() != "https":
                    raise UnsafeUrlError("redirect from HTTPS to plaintext HTTP is not allowed")
                current = target
                continue
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise ValueError(f"response exceeds the {max_bytes} byte limit")
            return FetchedPayload(
                url=current,
                status_code=response.status_code,
                headers={key.lower(): value for key, value in response.headers.items()},
                content=bytes(body),
            )
    raise UnsafeUrlError(f"too many redirects (maximum {MAX_REDIRECTS})")
