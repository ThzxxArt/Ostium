"""Strict validation for configurations accepted by ``ostium-core``.

The core service is privileged on clients (TUN) and binds public ports on
servers, so it must never trust the UI process.  This module enforces the
role-separated whitelist from PLAN.md §3.6 and §10.3 before ``sing-box check``.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any

from ostium.config import Role

TOP_LEVEL_KEYS = {"log", "dns", "inbounds", "outbounds", "route", "experimental", "ntp"}
SERVER_INBOUND_TYPES = {"vless", "hysteria2", "trojan", "shadowsocks"}
CLIENT_INBOUND_TYPES = {"tun", "mixed", "socks", "http"}
OUTBOUND_TYPES = {
    "direct",
    "block",
    "vless",
    "hysteria2",
    "trojan",
    "shadowsocks",
    "selector",
    "urltest",
    "dns",
}
EXPERIMENTAL_KEYS = {"clash_api", "v2ray_api", "cache_file"}
FORBIDDEN_KEYS = {
    "external_ui",
    "external_ui_download_url",
    "external_ui_download_detour",
    "services",
    "endpoints",
    "providers",
}


class ConfigRejected(ValueError):
    """The submitted configuration violates the core security policy."""

    def __init__(self, message: str, code: str = "invalid_config") -> None:
        super().__init__(message)
        self.code = code


def validate_config(
    config: Any,
    *,
    role: Role,
    allowed_ports: set[int],
    allowed_paths: list[Path],
    tun_interface: str = "ostium0",
) -> None:
    if not isinstance(config, dict):
        raise ConfigRejected("configuration must be a JSON object")
    _reject_forbidden_keys(config)
    unknown = set(config) - TOP_LEVEL_KEYS
    if unknown:
        raise ConfigRejected(f"unknown top-level keys: {sorted(unknown)}")
    if "inbounds" not in config or not isinstance(config["inbounds"], list):
        raise ConfigRejected("inbounds must be an array")
    if "outbounds" not in config or not isinstance(config["outbounds"], list):
        raise ConfigRejected("outbounds must be an array")

    tags: set[str] = set()
    for inbound in config["inbounds"]:
        if not isinstance(inbound, dict):
            raise ConfigRejected("each inbound must be an object")
        _validate_inbound(inbound, role, allowed_ports, tun_interface)
        tag = inbound.get("tag")
        if isinstance(tag, str):
            if tag in tags:
                raise ConfigRejected(f"duplicate inbound tag {tag!r}")
            tags.add(tag)
    outbound_tags: set[str] = set()
    for outbound in config["outbounds"]:
        if not isinstance(outbound, dict):
            raise ConfigRejected("each outbound must be an object")
        kind = outbound.get("type")
        if kind not in OUTBOUND_TYPES:
            raise ConfigRejected(f"outbound type {kind!r} is not allowed")
        tag = outbound.get("tag")
        if not isinstance(tag, str) or not tag:
            raise ConfigRejected("outbound tag is required")
        if tag in outbound_tags:
            raise ConfigRejected(f"duplicate outbound tag {tag!r}")
        outbound_tags.add(tag)

    experimental = config.get("experimental", {})
    if not isinstance(experimental, dict):
        raise ConfigRejected("experimental must be an object")
    unknown_exp = set(experimental) - EXPERIMENTAL_KEYS
    if unknown_exp:
        raise ConfigRejected(f"experimental keys not allowed: {sorted(unknown_exp)}")
    clash = experimental.get("clash_api")
    if clash is not None:
        if not isinstance(clash, dict):
            raise ConfigRejected("clash_api must be an object")
        controller = clash.get("external_controller", "")
        _require_loopback_controller(str(controller), "clash_api.external_controller")
    v2ray = experimental.get("v2ray_api")
    if v2ray is not None:
        if role is not Role.SERVER:
            raise ConfigRejected("v2ray_api is server-only", "role_mismatch")
        if not isinstance(v2ray, dict):
            raise ConfigRejected("v2ray_api must be an object")
        _require_loopback_controller(str(v2ray.get("listen", "")), "v2ray_api.listen")
    cache = experimental.get("cache_file")
    if cache is not None and not isinstance(cache, dict):
        raise ConfigRejected("cache_file must be an object")

    route = config.get("route", {})
    if not isinstance(route, dict):
        raise ConfigRejected("route must be an object")
    if role is Role.CLIENT and route.get("final") not in outbound_tags:
        raise ConfigRejected("route.final must reference a configured outbound")

    _validate_paths(config, allowed_paths)


def _validate_inbound(
    inbound: dict[str, Any], role: Role, allowed_ports: set[int], tun_interface: str
) -> None:
    kind = inbound.get("type")
    if role is Role.SERVER:
        if kind not in SERVER_INBOUND_TYPES:
            raise ConfigRejected(f"server inbound type {kind!r} is not allowed", "role_mismatch")
        if not isinstance(inbound.get("listen_port"), int):
            raise ConfigRejected("server inbound listen_port must be an integer")
        if inbound["listen_port"] not in allowed_ports:
            raise ConfigRejected(
                f"server inbound port {inbound['listen_port']} is not an approved proxy port",
                "port_not_allowed",
            )
        listen = str(inbound.get("listen", ""))
        if listen not in {"0.0.0.0", "::", ""} and not _is_local(listen):
            raise ConfigRejected("server inbound listen address is not allowed")
    else:
        if kind not in CLIENT_INBOUND_TYPES:
            raise ConfigRejected(f"client inbound type {kind!r} is not allowed", "role_mismatch")
        if kind in {"mixed", "socks", "http"}:
            if not _is_local(str(inbound.get("listen", ""))):
                raise ConfigRejected("client proxy inbound must bind to 127.0.0.1")
        if kind == "tun":
            interface = inbound.get("interface_name")
            if interface not in {tun_interface, "Ostium"}:
                raise ConfigRejected("TUN interface name is not the configured interface")
            stack = inbound.get("stack", "gvisor")
            if stack not in {"gvisor", "system", "mixed"}:
                raise ConfigRejected("TUN stack must be gvisor, system or mixed")
            mtu = inbound.get("mtu", 1500)
            if not isinstance(mtu, int) or not 1280 <= mtu <= 9000:
                raise ConfigRejected("TUN MTU must be between 1280 and 9000")
            if inbound.get("auto_route") is True and inbound.get("strict_route") not in {
                True,
                False,
                None,
            }:
                raise ConfigRejected("strict_route must be a boolean")


def _require_loopback_controller(value: str, field: str) -> None:
    host = value
    if value.startswith("http://"):
        host = value[7:]
    elif value.startswith("https://"):
        raise ConfigRejected(f"{field} must use plain HTTP on loopback")
    host = host.split("/", 1)[0]
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    if not _is_local(host):
        raise ConfigRejected(f"{field} must bind to a loopback address")


def _is_local(value: str) -> bool:
    host = value.strip().strip("[]")
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _reject_forbidden_keys(value: Any, depth: int = 0) -> None:
    if depth > 40:
        raise ConfigRejected("configuration nesting is too deep")
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_KEYS:
                raise ConfigRejected(f"key {key!r} is not allowed")
            _reject_forbidden_keys(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _reject_forbidden_keys(child, depth + 1)


def _validate_paths(value: Any, allowed_paths: list[Path], depth: int = 0) -> None:
    if depth > 40:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, str) and _looks_like_path(key, child):
                _check_path(child, allowed_paths)
            else:
                _validate_paths(child, allowed_paths, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _validate_paths(child, allowed_paths, depth + 1)


def _looks_like_path(key: str, value: str) -> bool:
    if key in {
        "certificate_path",
        "key_path",
        "path",
        "client_certificate_path",
        "client_key_path",
    }:
        return True
    return value.startswith("/") and key.endswith(("_path", "_file"))


def _check_path(raw: str, allowed_paths: list[Path]) -> None:
    if "\x00" in raw or ".." in Path(raw).parts:
        raise ConfigRejected("path traversal is not allowed", "path_not_allowed")
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise ConfigRejected("all file paths must be absolute", "path_not_allowed")
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise ConfigRejected("path cannot be resolved", "path_not_allowed") from exc
    for root in allowed_paths:
        try:
            root_resolved = root.resolve(strict=False)
            resolved.relative_to(root_resolved)
            return
        except (ValueError, OSError):
            continue
    raise ConfigRejected(f"path {raw!r} escapes the allowed directories", "path_not_allowed")
