from __future__ import annotations

import copy
from typing import Any

import pytest

from ostium.domain.endpoints import Endpoint, Protocol, TLSConfig
from ostium.engine.singbox.config import (
    CertificateSpec,
    ClientConfigSpec,
    ClientTunSpec,
    RealitySpec,
    ServerConfigSpec,
    ServerInbound,
    UserCredential,
    build_client_config,
    build_server_config,
    config_digest,
)


def _user(name: str = "alice") -> UserCredential:
    return UserCredential(
        name=name,
        uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
        password="password",
        ss_password="ss-password",
    )


def _inbound(kind: str, **kwargs: Any) -> ServerInbound:
    return ServerInbound(kind=kind, enabled=True, listen="0.0.0.0", port=443, **kwargs)


def _server(*inbounds: ServerInbound, **kwargs: Any) -> dict[str, Any]:
    return build_server_config(
        ServerConfigSpec(inbounds=list(inbounds), users=[_user()], clash_secret="secret", **kwargs)
    )


def test_server_all_inbound_types() -> None:
    reality = RealitySpec(
        private_key="private",
        short_id="short",
        server_name="sni.example",
        handshake_server="handshake.example",
        handshake_port=8443,
    )
    config = _server(
        _inbound("vless", reality=reality),
        _inbound(
            "hysteria2",
            certificate=CertificateSpec(cert_path="/tmp/cert.pem", key_path="/tmp/key.pem"),
            obfs_password="obfs",
        ),
        _inbound(
            "trojan",
            certificate=CertificateSpec(cert_path="/tmp/cert.pem", key_path="/tmp/key.pem"),
        ),
        _inbound("shadowsocks", ss_server_key="server-key"),
    )
    by_type = {item["type"]: item for item in config["inbounds"]}
    assert by_type["vless"]["tls"]["reality"]["handshake"] == {
        "server": "handshake.example",
        "server_port": 8443,
    }
    assert by_type["hysteria2"]["obfs"] == {"type": "salamander", "password": "obfs"}
    assert by_type["hysteria2"]["masquerade"]["status_code"] == 200
    assert by_type["trojan"]["users"][0]["password"] == "password"
    assert by_type["shadowsocks"]["password"] == "server-key"
    assert by_type["shadowsocks"]["users"][0]["password"] == "ss-password"
    assert config["experimental"]["v2ray_api"]["stats"]["users"] == ["alice"]


def test_server_skips_incomplete_and_disabled_inbounds() -> None:
    config = _server(
        _inbound("vless"),
        _inbound("hysteria2"),
        _inbound("trojan"),
        ServerInbound(kind="vless", enabled=False, port=443, reality=RealitySpec("p", "s")),
        ServerInbound(kind="unknown", enabled=True, port=443),
    )
    assert config["inbounds"] == []
    assert config["experimental"]["v2ray_api"]["stats"]["inbounds"] == []


def test_server_v2ray_and_egress_toggles() -> None:
    config = _server(_inbound("vless", reality=RealitySpec("p", "s")), enable_v2ray_api=False)
    assert "v2ray_api" not in config["experimental"]
    assert config["route"]["rules"][0]["ip_cidr"]
    config2 = _server(_inbound("vless", reality=RealitySpec("p", "s")), block_private_egress=False)
    assert config2["route"]["rules"] == [{"action": "reject", "port": [25]}]
    config3 = build_server_config(
        ServerConfigSpec(
            inbounds=[_inbound("vless", reality=RealitySpec("p", "s"))],
            users=[],
            clash_secret="s",
        ),
        include_v2ray_api=True,
    )
    assert config3["experimental"]["v2ray_api"]["stats"]["users"] == []


def test_server_shadowsocks_without_users_uses_empty_password() -> None:
    config = build_server_config(
        ServerConfigSpec(
            inbounds=[_inbound("shadowsocks")], users=[], clash_secret="s", enable_v2ray_api=False
        )
    )
    assert config["inbounds"][0]["password"] == ""
    assert config["inbounds"][0]["users"] == []


def _endpoint(tag: str = "hk", **kwargs: Any) -> Endpoint:
    defaults: dict[str, Any] = {
        "tag": tag,
        "protocol": Protocol.VLESS_REALITY,
        "name": tag,
        "server": "example.com",
        "port": 443,
        "uuid": "uuid",
        "tls": TLSConfig(server_name="sni", reality_public_key="pub", reality_short_id="sid"),
    }
    defaults.update(kwargs)
    return Endpoint(**defaults)


def test_client_multi_endpoint_urltest_and_selector() -> None:
    config = build_client_config(
        ClientConfigSpec(
            endpoints=[_endpoint("a"), _endpoint("b")],
            selected="b",
            routing_mode="global",
            clash_secret="secret",
        )
    )
    by_type = {item["type"]: item for item in config["outbounds"]}
    assert by_type["urltest"]["outbounds"] == ["a", "b"]
    assert by_type["selector"]["default"] == "b"
    assert by_type["selector"]["outbounds"] == ["auto", "a", "b"]
    assert "mixed" in [item["type"] for item in config["inbounds"]]
    assert config["route"]["final"] == "proxy"


def test_client_single_endpoint_and_direct_mode() -> None:
    config = build_client_config(
        ClientConfigSpec(
            endpoints=[_endpoint()], routing_mode="direct", clash_secret="", tun=ClientTunSpec()
        )
    )
    selector = next(item for item in config["outbounds"] if item["type"] == "selector")
    assert selector["default"] == "hk"
    assert selector["outbounds"] == ["hk"]
    assert config["route"]["final"] == "direct"
    assert config["experimental"]["clash_api"]["secret"] == "ostium-local"


def test_client_tun_variants() -> None:
    config = build_client_config(
        ClientConfigSpec(
            endpoints=[_endpoint()],
            mode="tun",
            tun=ClientTunSpec(
                enabled=True,
                interface_name="ostium0",
                mtu=1400,
                stack="system",
                auto_route=False,
                strict_route=False,
                dns_mode="hijack",
            ),
            ipv6=False,
            clash_secret="s",
        ),
        tun_interface="override0",
    )
    tun = next(item for item in config["inbounds"] if item["type"] == "tun")
    assert tun["interface_name"] == "override0"
    assert tun["address"] == ["172.19.0.1/30"]
    assert tun["mtu"] == 1400
    assert tun["auto_route"] is False
    assert tun["strict_route"] is False
    # mode=tun suppresses the mixed inbound unless tun is disabled.
    assert all(item["type"] != "mixed" for item in config["inbounds"])
    assert any(server["tag"] == "fakeip" for server in config["dns"]["servers"])
    assert config["dns"]["rules"][0]["server"] == "fakeip"


def test_client_tun_disabled_but_mode_tun_keeps_mixed() -> None:
    config = build_client_config(
        ClientConfigSpec(
            endpoints=[_endpoint()],
            mode="mixed",
            tun=ClientTunSpec(enabled=False, ipv6=True),
            clash_secret="s",
        )
    )
    assert [item["type"] for item in config["inbounds"]] == ["mixed"]
    assert config["dns"]["rules"] == [{"domain_suffix": [".cn"], "server": "local"}]


def test_client_custom_rules_and_rule_sets() -> None:
    config = build_client_config(
        ClientConfigSpec(
            endpoints=[_endpoint()],
            routing_mode="custom",
            rules=[
                {"domain": ["a.example"], "action": "direct", "ignored": "x"},
                {"domain_suffix": [".cn"], "action": "block"},
                {"ip_cidr": ["10.0.0.0/8"], "action": "proxy", "port": [443]},
            ],
            rule_sets=[
                {"name": "local", "path": "/tmp/local.srs"},
                {"tag": "remote", "url": "https://example.com/x.srs", "format": "source"},
                {"url": ""},
            ],
            clash_secret="s",
        )
    )
    rules = config["route"]["rules"]
    assert any(rule.get("action") == "reject" for rule in rules)
    assert any(rule.get("outbound") == "direct" for rule in rules)
    assert any(rule.get("outbound") == "proxy" and rule.get("port") == [443] for rule in rules)
    assert all("ignored" not in rule for rule in rules)
    sets = {item["tag"]: item for item in config["route"]["rule_set"]}
    assert sets["local"]["type"] == "local"
    assert sets["remote"]["format"] == "source"
    assert "url" not in sets["local"]


def test_client_requires_endpoint() -> None:
    with pytest.raises(ValueError):
        build_client_config(ClientConfigSpec(endpoints=[]))


def test_digest_is_order_independent_and_sensitive() -> None:
    left = {"a": 1, "b": [2, 3]}
    right = {"b": [2, 3], "a": 1}
    assert config_digest(left) == config_digest(right)
    assert config_digest(left) != config_digest({"a": 2, "b": [2, 3]})
    snapshot = copy.deepcopy(left)
    config_digest(left)
    assert left == snapshot
