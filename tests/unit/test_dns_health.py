"""DoH probing must be bounded, explicit and testable."""

from __future__ import annotations

import httpx
import pytest
import respx

from ostium.engine.dns import (
    DEFAULT_DOH_URL,
    DnsProbeResult,
    doh_host_and_path,
    probe_doh,
    select_server_dns,
)


def test_doh_host_and_path_defaults_to_cloudflare_sni() -> None:
    host, path, tls = doh_host_and_path("https://1.1.1.1/dns-query")
    assert (host, path, tls) == ("1.1.1.1", "/dns-query", "cloudflare-dns.com")
    host, path, tls = doh_host_and_path("https://dns.google/dns-query?x=1")
    assert (host, path, tls) == ("dns.google", "/dns-query?x=1", "dns.google")


def test_doh_rejects_non_https_urls() -> None:
    with pytest.raises(ValueError):
        doh_host_and_path("http://1.1.1.1/dns-query")


@respx.mock
def test_probe_doh_returns_answers() -> None:
    respx.get(DEFAULT_DOH_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "Status": 0,
                "Answer": [
                    {"name": "www.google.com.", "type": 5, "data": "example."},
                    {"name": "www.google.com.", "type": 1, "data": "142.251.152.119"},
                ],
            },
        )
    )
    result = probe_doh(DEFAULT_DOH_URL, timeout=1)
    assert result.ok is True
    assert result.answers == ("142.251.152.119",)
    assert result.error is None
    assert result.latency_ms is not None


@respx.mock
def test_probe_doh_reports_http_failure() -> None:
    respx.get(DEFAULT_DOH_URL).mock(return_value=httpx.Response(503))
    result = probe_doh(DEFAULT_DOH_URL, timeout=1)
    assert result.ok is False
    assert result.error


@respx.mock
def test_probe_doh_rejects_empty_answer() -> None:
    respx.get(DEFAULT_DOH_URL).mock(return_value=httpx.Response(200, json={"Status": 0}))
    result = probe_doh(DEFAULT_DOH_URL, timeout=1)
    assert result.ok is False
    assert "no A records" in (result.error or "")


def _probe(ok: bool) -> DnsProbeResult:
    return DnsProbeResult(
        ok=ok,
        url=DEFAULT_DOH_URL,
        latency_ms=10.0 if ok else None,
        answers=("1.2.3.4",) if ok else (),
        error=None if ok else "timed out",
        probed_at="2026-11-17T00:00:00+00:00",
    )


def test_select_auto_prefers_doh() -> None:
    selection = select_server_dns(mode="auto", doh_url=DEFAULT_DOH_URL, probe=_probe(True))
    assert selection.mode == "doh"
    assert selection.probe_ok is True
    assert selection.probed_at is not None


def test_select_auto_falls_back_to_udp() -> None:
    selection = select_server_dns(mode="auto", doh_url=DEFAULT_DOH_URL, probe=_probe(False))
    assert selection.mode == "udp"
    assert selection.probe_ok is False
    assert selection.probe_error == "timed out"


def test_select_doh_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="DoH is required"):
        select_server_dns(mode="doh", doh_url=DEFAULT_DOH_URL, probe=_probe(False))


def test_select_udp_skips_probe() -> None:
    selection = select_server_dns(mode="udp", doh_url=DEFAULT_DOH_URL, probe=_probe(False))
    assert selection.mode == "udp"
    assert selection.probed_at is None


def test_select_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        select_server_dns(mode="system", doh_url=DEFAULT_DOH_URL, probe=_probe(True))
