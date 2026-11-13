from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ostium.config import Role
from ostium.domain.endpoints import Endpoint, Protocol, TLSConfig
from ostium.engine.singbox.config import (
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
from ostium.engine.singbox.validate import ConfigRejected, validate_config


def _engine() -> Path | None:
    for candidate in (Path("/tmp/opencode/sing-box"), Path("/usr/local/bin/sing-box")):
        if candidate.is_file():
            return candidate
    return None


def test_config_digest_is_canonical() -> None:
    left = {"b": 2, "a": {"y": 1, "x": [1, 2]}}
    right = {"a": {"x": [1, 2], "y": 1}, "b": 2}
    assert config_digest(left) == config_digest(right)


def test_server_config_shape() -> None:
    spec = ServerConfigSpec(
        inbounds=[
            ServerInbound(
                kind="vless",
                enabled=True,
                listen="0.0.0.0",
                port=443,
                reality=RealitySpec(
                    private_key="private", short_id="abcd", server_name="www.apple.com"
                ),
            )
        ],
        users=[
            UserCredential(
                name="alice",
                uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
                password="pw",
                ss_password="c3M=",
            )
        ],
        clash_secret="secret",
    )
    config = build_server_config(spec)
    assert config["inbounds"][0]["type"] == "vless"
    assert config["experimental"]["v2ray_api"]["stats"]["users"] == ["alice"]
    assert config["route"]["final"] == "direct"


def test_client_config_shape() -> None:
    endpoint = Endpoint(
        tag="reality",
        protocol=Protocol.VLESS_REALITY,
        name="HK",
        server="vpn.example.com",
        port=443,
        uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
        tls=TLSConfig(
            server_name="www.apple.com",
            reality_public_key="Bs2KLXAKuw5pGFpBIwnyt896Y8mhNJHewMHHY0en6hM",
            reality_short_id="55e1651e",
        ),
    )
    config = build_client_config(
        ClientConfigSpec(endpoints=[endpoint], mixed_port=7890, clash_secret="secret")
    )
    assert config["inbounds"][0]["type"] == "mixed"
    assert config["inbounds"][0]["listen"] == "127.0.0.1"
    lan = build_client_config(
        ClientConfigSpec(
            endpoints=[endpoint],
            mixed_port=7890,
            allow_lan=True,
            clash_secret="secret",
        )
    )
    assert lan["inbounds"][0]["listen"] == "0.0.0.0"
    assert config["outbounds"][-2]["type"] == "selector"
    assert config["route"]["final"] == "proxy"
    assert config["route"]["rule_set"] == []


def test_client_tun_config_shape() -> None:
    endpoint = Endpoint(
        tag="reality",
        protocol=Protocol.VLESS_REALITY,
        name="HK",
        server="vpn.example.com",
        port=443,
        uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
        tls=TLSConfig(reality_public_key="pub", reality_short_id="sid"),
    )
    config = build_client_config(
        ClientConfigSpec(
            endpoints=[endpoint],
            mode="tun",
            tun=ClientTunSpec(enabled=True),
            clash_secret="secret",
        )
    )
    tun = config["inbounds"][0]
    assert tun["type"] == "tun"
    assert tun["interface_name"] == "ostium0"
    assert tun["strict_route"] is True
    assert "route_exclude_address" in tun


def test_validation_rejects_wrong_role() -> None:
    config = {
        "inbounds": [{"type": "tun", "tag": "tun-in", "interface_name": "ostium0"}],
        "outbounds": [{"type": "direct", "tag": "direct"}],
        "route": {"final": "direct"},
    }
    with pytest.raises(ConfigRejected):
        validate_config(
            config,
            role=Role.SERVER,
            allowed_ports={443},
            allowed_paths=[Path("/tmp")],
        )


def test_validation_rejects_bad_port_and_path() -> None:
    config = {
        "inbounds": [
            {
                "type": "trojan",
                "tag": "trojan-in",
                "listen": "0.0.0.0",
                "listen_port": 22,
                "users": [{"password": "x"}],
            }
        ],
        "outbounds": [{"type": "direct", "tag": "direct"}],
        "route": {"final": "direct"},
    }
    with pytest.raises(ConfigRejected):
        validate_config(config, role=Role.SERVER, allowed_ports={443}, allowed_paths=[Path("/tmp")])

    config["inbounds"][0]["listen_port"] = 443
    config["inbounds"][0]["tls"] = {
        "enabled": True,
        "certificate_path": "/etc/passwd",
        "key_path": "/etc/shadow",
    }
    with pytest.raises(ConfigRejected):
        validate_config(config, role=Role.SERVER, allowed_ports={443}, allowed_paths=[Path("/tmp")])


def test_validation_rejects_forbidden_experimental() -> None:
    config = {
        "inbounds": [
            {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 7890}
        ],
        "outbounds": [{"type": "direct", "tag": "direct"}],
        "route": {"final": "direct"},
        "experimental": {"external_ui": "x"},
    }
    with pytest.raises(ConfigRejected):
        validate_config(config, role=Role.CLIENT, allowed_ports=set(), allowed_paths=[Path("/tmp")])


@pytest.mark.integration
def test_generated_configs_pass_singbox_check(tmp_path: Path) -> None:
    engine = _engine()
    assert engine is not None, "sing-box binary is required for integration checks"
    endpoint = Endpoint(
        tag="reality",
        protocol=Protocol.VLESS_REALITY,
        name="HK",
        server="127.0.0.1",
        port=443,
        uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
        tls=TLSConfig(
            server_name="www.apple.com",
            reality_public_key="Bs2KLXAKuw5pGFpBIwnyt896Y8mhNJHewMHHY0en6hM",
            reality_short_id="55e1651e",
        ),
    )
    client_config = build_client_config(ClientConfigSpec(endpoints=[endpoint], clash_secret="test"))
    lan_config = build_client_config(
        ClientConfigSpec(endpoints=[endpoint], allow_lan=True, clash_secret="test")
    )
    validate_config(
        lan_config,
        role=Role.CLIENT,
        allowed_ports=set(),
        allowed_paths=[tmp_path],
        allow_lan=True,
    )
    server_config = build_server_config(
        ServerConfigSpec(
            inbounds=[
                ServerInbound(
                    kind="vless",
                    enabled=True,
                    listen="127.0.0.1",
                    port=443,
                    reality=RealitySpec(
                        private_key="IFxghqMsaCYgG6UXJM4998r_8OLm3U98Tt3SgzfB3Xk",
                        short_id="55e1651e1a99195b",
                    ),
                )
            ],
            users=[
                UserCredential(
                    name="alice",
                    uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
                    password="pw",
                    ss_password="c3M=",
                )
            ],
            clash_secret="test",
            enable_v2ray_api=False,
        )
    )
    for name, config in (
        ("client", client_config),
        ("client-lan", lan_config),
        ("server", server_config),
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(config))
        result = subprocess.run(
            [str(engine), "check", "-c", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
