from __future__ import annotations

import base64
import json

import pytest

from ostium.domain.endpoints import Endpoint, ProfileDocument
from ostium.services.profiles import ProfileError, parse_subscription_text

VLESS = (
    "vless://2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e@vpn.example.com:443"
    "?encryption=none&security=reality&sni=www.apple.com&fp=chrome"
    "&pbk=Bs2KLXAKuw5pGFpBIwnyt896Y8mhNJHewMHHY0en6hM&sid=55e1651e&type=tcp"
    "&flow=xtls-rprx-vision#HK%20Reality"
)

CLASH = """
proxies:
  - name: "HK Reality"
    type: vless
    server: vpn.example.com
    port: 443
    uuid: 2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e
    network: tcp
    tls: true
    servername: www.apple.com
    reality-opts:
      public-key: Bs2KLXAKuw5pGFpBIwnyt896Y8mhNJHewMHHY0en6hM
      short-id: "55e1651e"
    client-fingerprint: chrome
"""


def test_parse_uri_and_base64() -> None:
    endpoints = parse_subscription_text(VLESS)
    assert len(endpoints) == 1
    assert endpoints[0].name == "HK Reality"
    encoded = base64.b64encode(VLESS.encode()).decode()
    endpoints = parse_subscription_text(encoded)
    assert endpoints[0].protocol.value == "vless-reality"


def test_parse_clash() -> None:
    endpoints = parse_subscription_text(CLASH)
    assert len(endpoints) == 1
    assert endpoints[0].tls.reality_public_key


def test_parse_ostium_json() -> None:
    endpoint = Endpoint.from_uri(VLESS)
    document = ProfileDocument(name="test", endpoints=[endpoint])
    parsed = parse_subscription_text(document.to_json())
    assert parsed[0].tag == endpoint.tag


def test_parse_singbox_json() -> None:
    outbound = Endpoint.from_uri(VLESS).to_singbox_outbound()
    payload = json.dumps({"outbounds": [outbound]})
    parsed = parse_subscription_text(payload)
    assert parsed[0].port == 443


def test_invalid_input() -> None:
    with pytest.raises(ProfileError):
        parse_subscription_text("")
    with pytest.raises(ProfileError):
        parse_subscription_text("not a subscription")
