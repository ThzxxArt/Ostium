from __future__ import annotations

import socket

import pytest

from ostium.services.netguard import UnsafeUrlError, validate_remote_url


def _infos(*addresses: str) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses]


def test_literal_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    assert validate_remote_url("https://93.184.216.34/hook") == "https://93.184.216.34/hook"
    for url in (
        "http://127.0.0.1/x",
        "http://[::1]/x",
        "http://169.254.169.254/latest/meta-data",
        "http://169.254.1.1/",
        "http://100.100.100.200/",
        "http://224.0.0.1/",
        "ftp://example.com/x",
        "https://user:pass@example.com/x",
        "http://localhost/x",
    ):
        with pytest.raises(UnsafeUrlError):
            validate_remote_url(url)

    with pytest.raises(UnsafeUrlError):
        validate_remote_url("http://10.0.0.1/", allow_private=False)
    assert validate_remote_url("http://10.0.0.1/", allow_private=True) == "http://10.0.0.1/"


def test_dns_resolution_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _infos("93.184.216.34"))
    assert validate_remote_url("https://example.com/x") == "https://example.com/x"

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _infos("127.0.0.1"))
    with pytest.raises(UnsafeUrlError, match="blocked address"):
        validate_remote_url("https://example.com/x")

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _infos("fd00:ec2::254"))
    with pytest.raises(UnsafeUrlError):
        validate_remote_url("https://example.com/x")

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    with pytest.raises(UnsafeUrlError, match="could not resolve"):
        validate_remote_url("https://example.com/x")

    def fail(*args, **kwargs):
        raise socket.gaierror("no dns")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(UnsafeUrlError, match="could not resolve"):
        validate_remote_url("https://example.com/x")
