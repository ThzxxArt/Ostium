"""Server-side sing-box configuration generation.

The database is the only source of truth. This module never accepts arbitrary
JSON from an HTTP client; it derives a complete server configuration from the
enabled inbounds, active users and TLS inventory, validates it, and returns a
canonical hash for revision tracking.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from constance import config as runtime_config
from django.conf import settings
from pydantic import BaseModel, ConfigDict

from ostium import paths
from ostium.proxy.models import Inbound, ProxyUser
from ostium.proxy.services import config_queryset, enabled_inbounds

from .dns import DNSError, build_dns_plan


class ConfigError(RuntimeError):
    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log: dict[str, Any]
    dns: dict[str, Any]
    inbounds: list[dict[str, Any]]
    outbounds: list[dict[str, Any]]
    route: dict[str, Any]
    experimental: dict[str, Any]


@dataclass(slots=True)
class ConfigResult:
    config: dict[str, Any]
    sha256: str
    effective_dns: str
    warnings: list[str] = field(default_factory=list)

    @property
    def pretty(self) -> str:
        return json.dumps(self.config, indent=2, ensure_ascii=False) + "\n"


def canonical_json(config: dict[str, Any]) -> str:
    return json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(config).encode("utf-8")).hexdigest()


def _cert_path(certificate) -> tuple[Path, Path]:
    if certificate is None or not certificate.is_ready:
        raise ConfigError("A ready TLS certificate is required.")
    cert_file = certificate.cert_file.resolve()
    key_file = certificate.key_file.resolve()
    data_dir = paths.data_dir()
    for candidate in (cert_file, key_file):
        if not str(candidate).startswith(str(data_dir) + os.sep):
            raise ConfigError("Certificate path escapes the data directory.")
        if not candidate.is_file():
            raise ConfigError(f"Certificate file is missing: {candidate.name}")
    return cert_file, key_file


def _tls_block(certificate) -> dict[str, Any]:
    cert_file, key_file = _cert_path(certificate)
    return {"enabled": True, "certificate_path": str(cert_file), "key_path": str(key_file)}


def _reality_tls(params: dict[str, Any]) -> dict[str, Any]:
    server_name = params.get("server_name") or "www.microsoft.com"
    handshake = params.get("handshake_server") or server_name
    return {
        "enabled": True,
        "server_name": server_name,
        "reality": {
            "enabled": True,
            "handshake": {
                "server": handshake,
                "server_port": int(params.get("handshake_port") or 443),
            },
            "private_key": params["private_key"],
            "short_id": [params.get("short_id") or ""],
        },
    }


def _build_inbound(inbound: Inbound, users: list[ProxyUser]) -> dict[str, Any]:
    params = inbound.params
    common: dict[str, Any] = {
        "tag": f"{inbound.kind}-in",
        "listen": inbound.listen,
        "listen_port": inbound.port,
    }
    if inbound.kind == Inbound.Kind.VLESS:
        if not params.get("private_key"):
            raise ConfigError("VLESS Reality private key is missing.")
        return {
            "type": "vless",
            **common,
            "users": [{"name": user.name, "uuid": str(user.uuid), "flow": "xtls-rprx-vision"} for user in users],
            "tls": _reality_tls(params),
        }
    if inbound.kind == Inbound.Kind.HYSTERIA2:
        block: dict[str, Any] = {
            "type": "hysteria2",
            **common,
            "users": [{"name": user.name, "password": user.password} for user in users],
            "tls": _tls_block(inbound.certificate),
        }
        if params.get("obfs_password"):
            block["obfs"] = {"type": "salamander", "password": params["obfs_password"]}
        return block
    if inbound.kind == Inbound.Kind.TROJAN:
        return {
            "type": "trojan",
            **common,
            "users": [{"name": user.name, "password": user.password} for user in users],
            "tls": _tls_block(inbound.certificate),
        }
    if inbound.kind == Inbound.Kind.SHADOWSOCKS:
        if not params.get("server_key"):
            raise ConfigError("Shadowsocks server key is missing.")
        return {
            "type": "shadowsocks",
            **common,
            "method": params.get("method") or "2022-blake3-aes-128-gcm",
            "password": params["server_key"],
            "users": [{"name": user.name, "password": user.ss_password} for user in users],
        }
    raise ConfigError(f"Unsupported inbound kind: {inbound.kind}")


def _check_port_conflicts(inbounds: list[Inbound]) -> None:
    tcp: dict[int, str] = {}
    udp: dict[int, str] = {}
    for inbound in inbounds:
        if inbound.kind == Inbound.Kind.HYSTERIA2:
            if inbound.port in udp:
                raise ConfigError(f"UDP port {inbound.port} is used by both {udp[inbound.port]} and {inbound.kind}.")
            udp[inbound.port] = inbound.kind
        else:
            if inbound.port in tcp:
                raise ConfigError(f"TCP port {inbound.port} is used by both {tcp[inbound.port]} and {inbound.kind}.")
            tcp[inbound.port] = inbound.kind


def _acl_rules() -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = [
        {"action": "sniff"},
        {"protocol": "dns", "action": "hijack-dns"},
        {"port": [25], "network": "tcp", "action": "reject"},
        {
            "ip_cidr": [
                "169.254.169.254/32",
                "100.100.100.200/32",
                "fd00:ec2::254/128",
            ],
            "action": "reject",
        },
    ]
    if runtime_config.block_private_egress:
        rules.append({"ip_is_private": True, "action": "reject"})
    return rules


def _clash_secret() -> str:
    path = paths.clash_secret_path()
    paths.ensure_parent(path)
    if path.is_file():
        secret = path.read_text(encoding="utf-8").strip()
        if secret:
            return secret
    import secrets

    secret = secrets.token_urlsafe(32)
    path.write_text(secret, encoding="utf-8")
    paths.secure_file(path)
    return secret


_INBOUND_ORDER = {"vless": 0, "hysteria2": 1, "trojan": 2, "shadowsocks": 3}


def generate_config(*, probe_dns: bool = True) -> ConfigResult:
    inbounds = sorted(enabled_inbounds(), key=lambda inbound: _INBOUND_ORDER[inbound.kind])
    users = list(config_queryset())
    _check_port_conflicts(inbounds)

    errors: list[str] = []
    inbound_blocks: list[dict[str, Any]] = []
    for inbound in inbounds:
        try:
            errors.extend(inbound.validation_errors())
            if inbound.validation_errors():
                continue
            inbound_blocks.append(_build_inbound(inbound, users))
        except ConfigError as exc:
            errors.append(f"{inbound.kind}: {exc}")
    if errors:
        raise ConfigError("Inbound validation failed: " + "; ".join(errors), errors=errors)

    try:
        dns_plan = build_dns_plan(probe=probe_dns)
    except DNSError as exc:
        raise ConfigError(str(exc)) from exc

    warnings = []
    if dns_plan.warning:
        warnings.append(dns_plan.warning)

    user_names = [user.name for user in users]
    config: dict[str, Any] = {
        "log": {"level": runtime_config.log_level or "info", "timestamp": True},
        "dns": {
            "servers": dns_plan.servers,
            "final": dns_plan.final,
            "strategy": "ipv4_only",
        },
        "inbounds": inbound_blocks,
        "outbounds": [
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
        ],
        "route": {
            "rules": _acl_rules(),
            "final": "direct",
            "auto_detect_interface": True,
            "default_domain_resolver": dns_plan.final,
        },
        "experimental": {
            "clash_api": {
                "external_controller": settings.OSTIUM_SINGBOX_CLASH_ADDRESS,
                "secret": _clash_secret(),
                "default_mode": "rule",
            },
            "v2ray_api": {
                "listen": settings.OSTIUM_SINGBOX_STATS_ADDRESS,
                "stats": {
                    "enabled": True,
                    "inbounds": [block["tag"] for block in inbound_blocks],
                    "users": user_names,
                },
            },
        },
    }

    validated = ServerConfig.model_validate(config)
    payload = validated.model_dump(mode="json", exclude_none=True)
    return ConfigResult(
        config=payload,
        sha256=config_hash(payload),
        effective_dns=dns_plan.effective_mode,
        warnings=warnings,
    )


def write_config(path: Path, result: ConfigResult) -> None:
    paths.ensure_parent(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(result.pretty, encoding="utf-8")
    paths.secure_file(temp)
    temp.replace(path)


def check_config(binary: str, path: Path, *, timeout: int | None = None) -> tuple[bool, str]:
    import subprocess

    try:
        proc = subprocess.run(
            [binary, "check", "-c", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout or settings.OSTIUM_CONFIG_CHECK_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = (proc.stderr or proc.stdout or "").strip()
    return proc.returncode == 0, output[-4000:]


def is_private_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


__all__ = [
    "ConfigError",
    "ConfigResult",
    "ServerConfig",
    "check_config",
    "config_hash",
    "generate_config",
    "is_private_address",
    "write_config",
]
