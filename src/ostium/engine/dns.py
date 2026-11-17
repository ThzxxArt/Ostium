"""Encrypted DNS probing and server resolver selection.

UDP/53 was proven to be polluted on the deployment network: ``8.8.8.8`` and
``1.1.1.1`` returned the same wrong address while DoH returned the correct
records.  The server therefore prefers DoH and falls back to UDP only when the
operator chose ``auto`` and the encrypted probe fails.

The probe is deliberately small and bounded: one A query for
``www.google.com`` with no retries.  It runs in a worker thread so a blocked
network call never stalls the control-plane event loop.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from ostium.util.time import iso, utcnow

DEFAULT_DOH_URL = "https://1.1.1.1/dns-query"
DEFAULT_UDP_SERVER = "8.8.8.8"
PROBE_DOMAIN = "www.google.com"
PROBE_CACHE_SECONDS = 600.0
PROBE_TIMEOUT_SECONDS = 5.0

# IP literals cannot be used as the TLS server name.  Map the resolvers this
# project treats as trusted to their public names so certificate validation
# works when the operator keeps the default URL.
_DOH_SERVER_NAMES = {
    "1.1.1.1": "cloudflare-dns.com",
    "1.0.0.1": "cloudflare-dns.com",
    "8.8.8.8": "dns.google",
    "8.8.4.4": "dns.google",
    "9.9.9.9": "dns.quad9.net",
    "149.112.112.112": "dns.quad9.net",
}


@dataclass(frozen=True)
class DnsProbeResult:
    ok: bool
    url: str
    latency_ms: float | None
    answers: tuple[str, ...]
    error: str | None
    probed_at: str


@dataclass(frozen=True)
class ServerDnsSelection:
    mode: str
    doh_url: str
    probed_at: str | None
    probe_ok: bool
    probe_error: str | None


def doh_host_and_path(url: str) -> tuple[str, str, str | None]:
    """Split a DoH URL into ``(host, path, tls_server_name)``."""

    parsed = urlsplit(url.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("DoH URL must be an https:// URL with a host")
    host = parsed.hostname
    path = parsed.path or "/dns-query"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    tls_name = _DOH_SERVER_NAMES.get(host)
    if tls_name is None and not _is_ip_literal(host):
        tls_name = host
    return host, path, tls_name


def _is_ip_literal(value: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def probe_doh(
    url: str = DEFAULT_DOH_URL,
    *,
    timeout: float = PROBE_TIMEOUT_SECONDS,
    name: str = PROBE_DOMAIN,
) -> DnsProbeResult:
    """Query a DoH JSON endpoint and return a bounded, structured result."""

    import httpx

    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(2.0, timeout)), trust_env=False
        ) as client:
            response = client.get(
                url,
                params={"name": name, "type": "A"},
                headers={"Accept": "application/dns-json"},
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return DnsProbeResult(
            ok=False,
            url=url,
            latency_ms=None,
            answers=(),
            error=str(exc) or exc.__class__.__name__,
            probed_at=iso(utcnow()) or "",
        )
    latency = round((time.monotonic() - started) * 1000, 1)
    answers: list[str] = []
    if isinstance(payload, dict):
        for entry in payload.get("Answer") or []:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") not in {1, "1"}:
                continue
            data = entry.get("data")
            if isinstance(data, str) and data:
                answers.append(data)
    if not answers:
        return DnsProbeResult(
            ok=False,
            url=url,
            latency_ms=latency,
            answers=(),
            error="DoH response contained no A records",
            probed_at=iso(utcnow()) or "",
        )
    return DnsProbeResult(
        ok=True,
        url=url,
        latency_ms=latency,
        answers=tuple(answers),
        error=None,
        probed_at=iso(utcnow()) or "",
    )


def select_server_dns(
    *,
    mode: str,
    doh_url: str,
    probe: DnsProbeResult,
) -> ServerDnsSelection:
    """Resolve the configured policy into the mode actually applied."""

    requested = mode.strip().lower()
    if requested not in {"auto", "doh", "udp"}:
        raise ValueError("server_dns_mode must be auto, doh or udp")
    if requested == "udp":
        return ServerDnsSelection(
            mode="udp",
            doh_url=doh_url,
            probed_at=None,
            probe_ok=True,
            probe_error=None,
        )
    if requested == "doh" and not probe.ok:
        raise RuntimeError(f"DoH is required but the probe failed: {probe.error}")
    selected = "doh" if probe.ok else "udp"
    return ServerDnsSelection(
        mode=selected,
        doh_url=doh_url,
        probed_at=probe.probed_at,
        probe_ok=probe.ok,
        probe_error=probe.error,
    )
