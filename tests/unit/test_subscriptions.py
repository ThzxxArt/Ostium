"""Endpoint and renderer tests."""

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
import yaml

from ostium.proxy.models import Inbound
from ostium.subscriptions.endpoints import build_endpoints
from ostium.subscriptions.renderers import (
    content_type_for,
    extension_for,
    render,
    render_base64,
    render_clash,
    render_singbox,
)
from ostium.subscriptions.services import normalize_target


@pytest.fixture
def all_inbounds(inbounds, certificate):
    hysteria = Inbound.objects.get(kind="hysteria2")
    hysteria.certificate = certificate
    hysteria.enabled = True
    hysteria.save()
    trojan = Inbound.objects.get(kind="trojan")
    trojan.certificate = certificate
    trojan.enabled = True
    trojan.save()
    return inbounds


@pytest.mark.django_db
def test_build_endpoints_order_and_fields(proxy_user, all_inbounds):
    endpoints = build_endpoints(proxy_user, "vpn.example.com")
    assert [item.protocol for item in endpoints] == ["vless", "hysteria2", "trojan", "shadowsocks"]
    assert all(item.server == "vpn.example.com" for item in endpoints)
    assert endpoints[0].reality_public_key
    assert endpoints[1].password == proxy_user.password
    assert endpoints[2].sni == "vpn.example.com"
    assert endpoints[3].ss_password == f"{all_inbounds[-1].params['server_key']}:{proxy_user.ss_password}"


@pytest.mark.django_db
def test_disabled_inbound_is_skipped(proxy_user, inbounds):
    for inbound in inbounds:
        inbound.enabled = False
        inbound.save(update_fields=["enabled"])
    assert build_endpoints(proxy_user, "vpn.example.com") == []


@pytest.mark.django_db
def test_uri_formats(proxy_user, all_inbounds):
    endpoints = build_endpoints(proxy_user, "vpn.example.com")
    vless = endpoints[0].to_uri()
    parsed = urlsplit(vless)
    assert parsed.scheme == "vless"
    query = parse_qs(parsed.query)
    assert query["security"] == ["reality"]
    assert query["pbk"] == [endpoints[0].reality_public_key]
    assert query["flow"] == ["xtls-rprx-vision"]
    assert unquote(parsed.fragment) == "vpn.example.com · Reality"

    hysteria = endpoints[1].to_uri()
    assert hysteria.startswith("hysteria2://")
    assert "pinSHA256=" in hysteria

    trojan = endpoints[2].to_uri()
    assert trojan.startswith("trojan://")

    ss = endpoints[3].to_uri()
    payload = ss.removeprefix("ss://").split("@", 1)[0]
    decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
    assert decoded == f"{endpoints[3].method}:{endpoints[3].ss_password}"


@pytest.mark.django_db
def test_base64_round_trip(proxy_user, all_inbounds):
    endpoints = build_endpoints(proxy_user, "vpn.example.com")
    encoded = render_base64(endpoints)
    decoded = base64.b64decode(encoded).decode()
    assert decoded.count("\n") == 4
    assert decoded.startswith("vless://")


@pytest.mark.django_db
def test_clash_yaml(proxy_user, all_inbounds):
    endpoints = build_endpoints(proxy_user, "vpn.example.com")
    payload = yaml.safe_load(render_clash(endpoints))
    assert payload["mixed-port"] == 7890
    assert len(payload["proxies"]) == 4
    assert payload["proxy-groups"][0]["name"] == "Ostium"
    assert payload["rules"][-1] == "MATCH,Ostium"
    assert payload["proxies"][0]["reality-opts"]["public-key"]


@pytest.mark.django_db
def test_singbox_json(proxy_user, all_inbounds):
    endpoints = build_endpoints(proxy_user, "vpn.example.com")
    payload = json.loads(render_singbox(endpoints))
    assert payload["inbounds"][0]["listen_port"] == 7890
    assert payload["route"]["final"] == "Ostium"
    tags = [outbound["tag"] for outbound in payload["outbounds"]]
    assert "Auto" in tags and "Ostium" in tags
    assert payload["outbounds"][0]["tls"]["reality"]["public_key"]


@pytest.mark.django_db
def test_render_dispatch(proxy_user, all_inbounds):
    endpoints = build_endpoints(proxy_user, "vpn.example.com")
    for target in ("base64", "uri", "clash", "singbox"):
        assert render(target, endpoints)
        assert content_type_for(target)
        assert extension_for(target)
    with pytest.raises(ValueError):
        render("unknown", endpoints)


def test_normalize_target():
    assert normalize_target(None) == "base64"
    assert normalize_target("base64") == "base64"
    assert normalize_target("sing-box") == "singbox"
    assert normalize_target("clash-meta") == "clash"
    assert normalize_target("nope") is None
