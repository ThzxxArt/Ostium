"""Config generation for every protocol and endpoint error branches."""

from __future__ import annotations

import pytest

from ostium.engine.config import ConfigError, _cert_path, generate_config
from ostium.proxy.models import Inbound
from ostium.subscriptions.endpoints import Endpoint, build_endpoints


@pytest.mark.django_db
def test_tls_protocols_config(proxy_user, inbounds, certificate):
    for kind in ("hysteria2", "trojan"):
        inbound = Inbound.objects.get(kind=kind)
        inbound.enabled = True
        inbound.certificate = certificate
        if kind == "trojan":
            inbound.port = 8444
        inbound.save()
    result = generate_config(probe_dns=False)
    types = {block["type"] for block in result.config["inbounds"]}
    assert {"vless", "hysteria2", "trojan", "shadowsocks"} <= types
    hysteria = next(block for block in result.config["inbounds"] if block["type"] == "hysteria2")
    assert hysteria["tls"]["certificate_path"].endswith("fullchain.pem")
    assert hysteria["obfs"]["type"] == "salamander"
    trojan = next(block for block in result.config["inbounds"] if block["type"] == "trojan")
    assert trojan["users"][0]["name"] == proxy_user.name


@pytest.mark.django_db
def test_cert_path_escapes_data_dir(certificate, settings, tmp_path):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    certificate.cert_path = "../../etc/passwd"
    with pytest.raises(ConfigError):
        _cert_path(certificate)


@pytest.mark.django_db
def test_certificate_not_ready(inbounds):
    inbound = Inbound.objects.get(kind="trojan")
    inbound.enabled = True
    inbound.save()
    with pytest.raises(ConfigError):
        generate_config(probe_dns=False)


def test_endpoint_unsupported():
    endpoint = Endpoint(protocol="unknown", label="x", server="h", port=1, name="n")
    with pytest.raises(ValueError):
        endpoint.to_uri()
    with pytest.raises(ValueError):
        endpoint.to_clash_proxy()
    with pytest.raises(ValueError):
        endpoint.to_singbox_outbound()


def test_endpoint_ipv6_host():
    endpoint = Endpoint(
        protocol="trojan",
        label="T",
        server="2001:db8::1",
        port=443,
        name="v6",
        password="p",
        sni="example.com",
    )
    assert "[2001:db8::1]" in endpoint.to_uri()


@pytest.mark.django_db
def test_build_endpoints_skips_incomplete(proxy_user, inbounds):
    vless = Inbound.objects.get(kind="vless")
    vless.update_params(public_key="")
    vless.save()
    ss = Inbound.objects.get(kind="shadowsocks")
    ss.update_params(server_key="")
    ss.save()
    assert build_endpoints(proxy_user, "vpn.example.com") == []
