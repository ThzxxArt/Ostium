from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from ostium.config import Role
from ostium.engine.singbox.validate import (
    ConfigRejected,
    _is_local,
    _require_loopback_controller,
    validate_config,
)


def _server(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "log": {"level": "info"},
        "inbounds": [
            {
                "type": "vless",
                "tag": "vless-in",
                "listen": "0.0.0.0",
                "listen_port": 443,
            }
        ],
        "outbounds": [{"type": "direct", "tag": "direct"}],
        "route": {"final": "direct"},
        "experimental": {
            "clash_api": {"external_controller": "127.0.0.1:19090"},
            "v2ray_api": {"listen": "127.0.0.1:19091"},
        },
    }
    config.update(overrides)
    return config


def _client(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "log": {"level": "info"},
        "inbounds": [
            {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 7890}
        ],
        "outbounds": [
            {"type": "vless", "tag": "proxy"},
            {"type": "direct", "tag": "direct"},
        ],
        "route": {"final": "proxy"},
        "experimental": {"clash_api": {"external_controller": "127.0.0.1:19090"}},
    }
    config.update(overrides)
    return config


def _validate(config: Any, role: Role, tmp_path: Path) -> None:
    validate_config(
        config,
        role=role,
        allowed_ports={443, 8388},
        allowed_paths=[tmp_path, tmp_path / "certs"],
        tun_interface="ostium0",
    )


def test_valid_server_and_client(tmp_path: Path) -> None:
    _validate(_server(), Role.SERVER, tmp_path)
    _validate(_client(), Role.CLIENT, tmp_path)
    _validate(_server(inbounds=[]), Role.SERVER, tmp_path)
    _validate(_client(inbounds=[]), Role.CLIENT, tmp_path)


@pytest.mark.parametrize(
    ("config", "code"),
    [
        ([], "invalid_config"),
        (_server(unknown=True), "invalid_config"),
        (_server(inbounds={}), "invalid_config"),
        (_server(inbounds="x"), "invalid_config"),
        (_server(outbounds={}), "invalid_config"),
        (_server(outbounds="x"), "invalid_config"),
        (_server(inbounds=[1]), "invalid_config"),
        (_server(outbounds=[1]), "invalid_config"),
        (_server(inbounds=[{"type": "http", "listen_port": 443}]), "role_mismatch"),
        (
            _server(inbounds=[{"type": "vless", "listen": "0.0.0.0", "listen_port": "443"}]),
            "invalid_config",
        ),
        (
            _server(inbounds=[{"type": "vless", "listen": "0.0.0.0", "listen_port": 80}]),
            "port_not_allowed",
        ),
        (
            _server(inbounds=[{"type": "vless", "listen": "8.8.8.8", "listen_port": 443}]),
            "invalid_config",
        ),
        (
            _server(
                inbounds=[
                    {"type": "vless", "tag": "same", "listen_port": 443},
                    {"type": "trojan", "tag": "same", "listen_port": 443},
                ]
            ),
            "invalid_config",
        ),
        (_server(outbounds=[{"type": "wireguard", "tag": "x"}]), "invalid_config"),
        (_server(outbounds=[{"type": "direct"}]), "invalid_config"),
        (
            _server(
                outbounds=[
                    {"type": "direct", "tag": "same"},
                    {"type": "block", "tag": "same"},
                ]
            ),
            "invalid_config",
        ),
        (_server(experimental="x"), "invalid_config"),
        (_server(experimental={"external_ui": "x"}), "invalid_config"),
        (_server(experimental={"clash_api": "x"}), "invalid_config"),
        (
            _server(experimental={"clash_api": {"external_controller": "8.8.8.8:9090"}}),
            "invalid_config",
        ),
        (
            _server(experimental={"clash_api": {"external_controller": "https://127.0.0.1:9090"}}),
            "invalid_config",
        ),
        (_server(experimental={"v2ray_api": "x"}), "invalid_config"),
        (
            _server(experimental={"v2ray_api": {"listen": "0.0.0.0:19091"}}),
            "invalid_config",
        ),
        (_server(experimental={"cache_file": []}), "invalid_config"),
        (_server(route="x"), "invalid_config"),
        (_server(route={"rules": [{"external_ui": "x"}]}), "invalid_config"),
    ],
)
def test_validation_rejections(config: Any, code: str, tmp_path: Path) -> None:
    with pytest.raises(ConfigRejected) as excinfo:
        _validate(config, Role.SERVER, tmp_path)
    assert excinfo.value.code == code


def test_client_route_final_must_reference_outbound(tmp_path: Path) -> None:
    with pytest.raises(ConfigRejected):
        _validate(_client(route={"final": "missing"}), Role.CLIENT, tmp_path)


def test_client_v2ray_api_is_server_only(tmp_path: Path) -> None:
    config = _client(experimental={"v2ray_api": {"listen": "127.0.0.1:19091"}})
    with pytest.raises(ConfigRejected) as excinfo:
        _validate(config, Role.CLIENT, tmp_path)
    assert excinfo.value.code == "role_mismatch"


@pytest.mark.parametrize(
    "inbound",
    [
        {"type": "wireguard", "listen": "127.0.0.1"},
        {"type": "mixed", "listen": "0.0.0.0"},
        {"type": "socks", "listen": "192.168.1.1"},
        {"type": "tun", "interface_name": "other", "stack": "gvisor"},
        {"type": "tun", "interface_name": "ostium0", "stack": "bad"},
        {"type": "tun", "interface_name": "ostium0", "mtu": "1500"},
        {"type": "tun", "interface_name": "ostium0", "mtu": 1000},
        {"type": "tun", "interface_name": "Ostium", "strict_route": "yes", "auto_route": True},
    ],
)
def test_client_inbound_rejections(inbound: dict[str, Any], tmp_path: Path) -> None:
    with pytest.raises(ConfigRejected):
        _validate(_client(inbounds=[inbound]), Role.CLIENT, tmp_path)


@pytest.mark.parametrize(
    ("inbound", "accepted"),
    [
        ({"type": "tun", "interface_name": "ostium0", "stack": "system", "mtu": 1280}, True),
        ({"type": "tun", "interface_name": "Ostium", "stack": "mixed", "mtu": 9000}, True),
        (
            {
                "type": "tun",
                "interface_name": "ostium0",
                "auto_route": True,
                "strict_route": False,
            },
            True,
        ),
        ({"type": "socks", "listen": "localhost"}, True),
        ({"type": "http", "listen": "127.0.0.1"}, True),
    ],
)
def test_client_inbound_acceptance(inbound: dict[str, Any], accepted: bool, tmp_path: Path) -> None:
    _validate(_client(inbounds=[inbound]), Role.CLIENT, tmp_path)
    assert accepted


def test_server_listen_variants(tmp_path: Path) -> None:
    for listen in ("0.0.0.0", "::", "", "127.0.0.1", "::1", "localhost"):
        _validate(
            _server(inbounds=[{"type": "vless", "listen": listen, "listen_port": 443}]),
            Role.SERVER,
            tmp_path,
        )


def test_forbidden_keys_at_depth_and_arrays(tmp_path: Path) -> None:
    nested = _server()
    nested["route"]["rules"] = [{"nested": [{"external_ui": "x"}]}]
    with pytest.raises(ConfigRejected):
        _validate(nested, Role.SERVER, tmp_path)

    deep: dict[str, Any] = {}
    cursor = deep
    for _ in range(45):
        child: dict[str, Any] = {}
        cursor["child"] = child
        cursor = child
    with pytest.raises(ConfigRejected):
        _validate(_server(route=deep), Role.SERVER, tmp_path)


def test_path_validation(tmp_path: Path) -> None:
    allowed_cert = tmp_path / "certs" / "fullchain.pem"
    allowed_cert.parent.mkdir()
    allowed_cert.write_text("x")
    config = _server(
        inbounds=[
            {
                "type": "trojan",
                "tag": "trojan-in",
                "listen_port": 443,
                "tls": {
                    "certificate_path": str(allowed_cert),
                    "key_path": str(tmp_path / "key.pem"),
                },
            }
        ]
    )
    _validate(config, Role.SERVER, tmp_path)

    for bad in ("relative.pem", "../escape.pem", "/etc/passwd", str(tmp_path / "a\x00b")):
        broken = _server(
            inbounds=[
                {
                    "type": "trojan",
                    "listen_port": 443,
                    "tls": {"certificate_path": bad},
                }
            ]
        )
        with pytest.raises(ConfigRejected) as excinfo:
            _validate(broken, Role.SERVER, tmp_path)
        assert excinfo.value.code == "path_not_allowed"

    # Unknown *_path keys are still inspected when the value is absolute.
    broken = _server(route={"rules": [{"custom_path": "/etc/shadow"}]})
    with pytest.raises(ConfigRejected):
        _validate(broken, Role.SERVER, tmp_path)


def test_path_depth_limit_returns_without_error(tmp_path: Path) -> None:
    from ostium.engine.singbox.validate import _validate_paths

    payload: dict[str, Any] = {"leaf": "/etc/passwd"}
    for _ in range(45):
        payload = {"child": payload}
    _validate_paths(payload, [tmp_path])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("localhost", True),
        ("127.0.0.1", True),
        ("::1", True),
        ("[::1]", True),
        ("127.0.0.2", True),
        ("8.8.8.8", False),
        ("example.com", False),
        ("", False),
    ],
)
def test_is_local(value: str, expected: bool) -> None:
    assert _is_local(value) is expected


@pytest.mark.parametrize(
    "value",
    [
        "127.0.0.1:9090",
        "http://127.0.0.1:9090",
        "http://localhost:9090/path",
        "[::1]:9090",
    ],
)
def test_loopback_controller_accepts(value: str) -> None:
    _require_loopback_controller(value, "x")


@pytest.mark.parametrize(
    "value",
    ["https://127.0.0.1:9090", "8.8.8.8:9090", "http://example.com:9090", "", "::1"],
)
def test_loopback_controller_rejects(value: str) -> None:
    with pytest.raises(ConfigRejected):
        _require_loopback_controller(value, "x")


def test_validation_does_not_mutate_input(tmp_path: Path) -> None:
    config = _server()
    snapshot = copy.deepcopy(config)
    _validate(config, Role.SERVER, tmp_path)
    assert config == snapshot
