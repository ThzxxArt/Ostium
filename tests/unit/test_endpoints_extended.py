from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ostium.domain.endpoints import (
    Endpoint,
    ProfileDocument,
    Protocol,
    TLSConfig,
    _host,
    _query,
    _slug,
)


def _endpoint(kind: Protocol = Protocol.VLESS_REALITY, **overrides: object) -> Endpoint:
    defaults: dict[str, object] = {
        "tag": "hk-1",
        "protocol": kind,
        "name": "HK 节点",
        "server": "vpn.example.com",
        "port": 443,
        "uuid": "2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
        "password": "secret",
        "tls": TLSConfig(
            server_name="www.apple.com",
            reality_public_key="pub",
            reality_short_id="sid",
        ),
    }
    defaults.update(overrides)
    return Endpoint(**defaults)  # type: ignore[arg-type]


def test_singbox_outbounds_all_protocols() -> None:
    vless = _endpoint().to_singbox_outbound()
    assert vless["type"] == "vless"
    assert vless["tls"]["reality"]["public_key"] == "pub"
    assert vless["tls"]["utls"]["fingerprint"] == "chrome"

    hy2 = _endpoint(Protocol.HYSTERIA2).to_singbox_outbound()
    assert hy2["type"] == "hysteria2"
    assert hy2["tls"]["server_name"] == "www.apple.com"
    assert hy2["tls"]["insecure"] is False
    assert "certificate_sha256" not in hy2["tls"]

    trojan = _endpoint(Protocol.TROJAN).to_singbox_outbound()
    assert trojan["type"] == "trojan"
    assert trojan["password"] == "secret"

    ss = _endpoint(Protocol.SHADOWSOCKS).to_singbox_outbound()
    assert ss["type"] == "shadowsocks"
    assert ss["method"] == "2022-blake3-aes-128-gcm"
    assert ss["udp_over_tcp"] is False


def test_tls_pin_and_empty_flow() -> None:
    endpoint = _endpoint(
        Protocol.HYSTERIA2,
        tls=TLSConfig(server_name="x", insecure=True, certificate_pin_sha256="pin"),
    )
    outbound = endpoint.to_singbox_outbound()
    assert outbound["tls"]["insecure"] is True
    assert outbound["tls"]["certificate_sha256"] == "pin"
    assert endpoint.to_clash_proxy()["fingerprint"] == "pin"
    assert endpoint.to_uri().endswith("#HK%20%E8%8A%82%E7%82%B9")

    vless = _endpoint(flow="")
    assert "flow" not in vless.to_singbox_outbound()


def test_clash_proxy_shapes() -> None:
    vless = _endpoint().to_clash_proxy()
    assert vless["type"] == "vless"
    assert vless["reality-opts"]["short-id"] == "sid"
    assert vless["client-fingerprint"] == "chrome"

    hy2 = _endpoint(Protocol.HYSTERIA2).to_clash_proxy()
    assert hy2["type"] == "hysteria2"
    assert hy2["skip-cert-verify"] is False

    trojan = _endpoint(Protocol.TROJAN).to_clash_proxy()
    assert trojan["type"] == "trojan"

    ss = _endpoint(Protocol.SHADOWSOCKS).to_clash_proxy()
    assert ss["type"] == "ss"
    assert ss["plugin"] == ""


def test_uri_generation_variants() -> None:
    assert _endpoint().to_uri().startswith("vless://2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e@")
    assert "security=reality" in _endpoint().to_uri()
    assert "insecure=1" in _endpoint(Protocol.HYSTERIA2, tls=TLSConfig(insecure=True)).to_uri()
    assert (
        "pinSHA256=pin"
        in _endpoint(Protocol.HYSTERIA2, tls=TLSConfig(certificate_pin_sha256="pin")).to_uri()
    )
    assert _endpoint(Protocol.TROJAN).to_uri().startswith("trojan://secret@")
    assert _endpoint(Protocol.SHADOWSOCKS).to_uri().startswith("ss://")
    ipv6 = _endpoint(server="2001:db8::1")
    assert "@[2001:db8::1]:443" in ipv6.to_uri()
    bracketed = _endpoint(server="[2001:db8::1]")
    assert "@[2001:db8::1]:443" in bracketed.to_uri()


def test_from_uri_vless_defaults_and_alias() -> None:
    endpoint = Endpoint.from_uri(
        "vless://uuid@example.com:443?encryption=none&sni=sni.example&pbk=key&sid=01&fp=firefox#Name"
    )
    assert endpoint.protocol is Protocol.VLESS_REALITY
    assert endpoint.tls.server_name == "sni.example"
    assert endpoint.tls.fingerprint == "firefox"
    assert endpoint.flow == "xtls-rprx-vision"

    hy2 = Endpoint.from_uri("hy2://pass@example.com:8443?sni=x&insecure=true#HY")
    assert hy2.protocol is Protocol.HYSTERIA2
    assert hy2.password == "pass"
    assert hy2.tls.insecure is True
    assert hy2.tls.server_name == "x"

    trojan = Endpoint.from_uri("trojan://pass@example.com:443?peer=x&allowInsecure=1#T")
    assert trojan.protocol is Protocol.TROJAN
    assert trojan.tls.insecure is True
    assert trojan.tls.server_name == "x"


def test_from_uri_shadowsocks_and_errors() -> None:
    userinfo = "MjAyMi1ibGFrZTMtYWVzLTEyOC1nY206cGFzcw"
    endpoint = Endpoint.from_uri(f"ss://{userinfo}@example.com:8388#SS")
    assert endpoint.protocol is Protocol.SHADOWSOCKS
    assert endpoint.method == "2022-blake3-aes-128-gcm"
    assert endpoint.password == "pass"

    with pytest.raises(ValueError):
        Endpoint.from_uri("ss://bm90LWNvbG9u@example.com:8388")
    with pytest.raises(ValueError):
        Endpoint.from_uri("ss://!!!@example.com:8388")
    with pytest.raises(ValueError):
        Endpoint.from_uri("vmess://whatever")
    with pytest.raises(ValueError):
        Endpoint.from_uri("not a uri")


def test_tag_validation() -> None:
    for bad in ("", "a" * 65, 'bad"tag', "bad\\tag", "bad\ntag"):
        with pytest.raises(ValidationError):
            _endpoint(tag=bad)


def test_profile_document_roundtrip_and_rejection() -> None:
    document = ProfileDocument(name="HK", endpoints=[_endpoint()])
    dumped = document.to_json()
    assert json.loads(dumped)["format"] == "ostium-profile"
    parsed = ProfileDocument.from_json(dumped)
    assert parsed.endpoints[0].tag == "hk-1"

    minimal = json.dumps({"name": "x", "endpoints": [json.loads(_endpoint().model_dump_json())]})
    assert ProfileDocument.from_json(minimal).name == "x"
    with pytest.raises(ValueError):
        ProfileDocument.from_json('{"format": "other", "name": "x", "endpoints": []}')


def test_private_helpers() -> None:
    assert _host("example.com") == "example.com"
    assert _host("2001:db8::1") == "[2001:db8::1]"
    assert _host("[2001:db8::1]") == "[2001:db8::1]"
    assert _query({"a": "1", "b": "", "c": "x y"}) == "a=1&c=x%20y"
    assert _slug("Hello World!") == "hello-world"
    assert _slug("!!!") == "endpoint"
    assert len(_slug("a" * 100)) == 64
