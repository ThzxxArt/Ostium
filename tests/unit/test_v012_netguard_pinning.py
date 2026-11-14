"""The outbound fetcher must connect to the address it validated."""

from __future__ import annotations

import socket

from ostium.services.netguard import _pin_dns, resolve_remote_url


def test_resolve_remote_url_returns_the_validated_addresses(monkeypatch) -> None:
    def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        assert host == "example.com"
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    target = resolve_remote_url("https://example.com/file")
    assert target.host == "example.com"
    assert target.addresses == ("93.184.216.34",)


def test_pin_dns_replaces_the_answer_used_by_the_http_client(monkeypatch) -> None:
    calls: list[str] = []

    def fake_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with _pin_dns("example.com", ("93.184.216.34",)):
        socket.getaddrinfo("example.com", 443)
        socket.getaddrinfo("other.example", 443)
    assert calls == ["93.184.216.34", "other.example"]
