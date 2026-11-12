from __future__ import annotations

import json

import pytest

from ostium.domain.endpoints import Endpoint, ProfileDocument, Protocol, TLSConfig


def reality() -> Endpoint:
    return Endpoint(
        tag="alice-reality",
        protocol=Protocol.VLESS_REALITY,
        name="HK Reality",
        server="vpn.example.com",
        port=443,
        uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
        tls=TLSConfig(
            server_name="www.apple.com",
            reality_public_key="Bs2KLXAKuw5pGFpBIwnyt896Y8mhNJHewMHHY0en6hM",
            reality_short_id="55e1651e",
        ),
    )


def test_vless_uri_roundtrip() -> None:
    endpoint = reality()
    uri = endpoint.to_uri()
    assert uri.startswith("vless://")
    parsed = Endpoint.from_uri(uri)
    assert parsed.protocol is Protocol.VLESS_REALITY
    assert parsed.uuid == endpoint.uuid
    assert parsed.server == endpoint.server
    assert parsed.tls.reality_public_key == endpoint.tls.reality_public_key
    assert parsed.tls.reality_short_id == endpoint.tls.reality_short_id


def test_hysteria2_uri_roundtrip() -> None:
    endpoint = Endpoint(
        tag="hy2",
        protocol=Protocol.HYSTERIA2,
        name="HK Hysteria2",
        server="vpn.example.com",
        port=443,
        password="p@ss word",
        tls=TLSConfig(server_name="vpn.example.com", insecure=True),
    )
    parsed = Endpoint.from_uri(endpoint.to_uri())
    assert parsed.protocol is Protocol.HYSTERIA2
    assert parsed.password == "p@ss word"
    assert parsed.tls.insecure


def test_trojan_uri_roundtrip() -> None:
    endpoint = Endpoint(
        tag="trojan",
        protocol=Protocol.TROJAN,
        name="Trojan",
        server="203.0.113.10",
        port=443,
        password="secret",
        tls=TLSConfig(server_name="vpn.example.com"),
    )
    parsed = Endpoint.from_uri(endpoint.to_uri())
    assert parsed.protocol is Protocol.TROJAN
    assert parsed.server == "203.0.113.10"


def test_shadowsocks_uri_roundtrip() -> None:
    endpoint = Endpoint(
        tag="ss",
        protocol=Protocol.SHADOWSOCKS,
        name="SS2022",
        server="vpn.example.com",
        port=8388,
        method="2022-blake3-aes-128-gcm",
        password="F3S0YbT9bZ0n4G0hV0l1zA==",
        tls=TLSConfig(enabled=False),
    )
    parsed = Endpoint.from_uri(endpoint.to_uri())
    assert parsed.protocol is Protocol.SHADOWSOCKS
    assert parsed.method == endpoint.method
    assert parsed.password == endpoint.password


def test_unsupported_uri() -> None:
    with pytest.raises(ValueError):
        Endpoint.from_uri("vmess://something")


def test_singbox_and_clash_shapes() -> None:
    endpoint = reality()
    outbound = endpoint.to_singbox_outbound()
    assert outbound["type"] == "vless"
    assert outbound["tls"]["reality"]["public_key"]
    proxy = endpoint.to_clash_proxy()
    assert proxy["type"] == "vless"
    assert proxy["reality-opts"]["short-id"] == endpoint.tls.reality_short_id


def test_profile_document_json() -> None:
    document = ProfileDocument(name="test", endpoints=[reality()])
    payload = document.to_json()
    parsed = ProfileDocument.from_json(payload)
    assert parsed.format == "ostium-profile"
    assert parsed.version == 1
    assert parsed.endpoints[0].tag == "alice-reality"
    assert json.loads(payload)["endpoints"][0]["server"] == "vpn.example.com"
