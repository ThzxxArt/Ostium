"""Proxy endpoint model shared by config generation, subscriptions and imports."""

from __future__ import annotations

import base64
import json
from enum import StrEnum
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from pydantic import BaseModel, Field, field_validator

from ostium import PROFILE_FORMAT_VERSION


class Protocol(StrEnum):
    VLESS_REALITY = "vless-reality"
    HYSTERIA2 = "hysteria2"
    TROJAN = "trojan"
    SHADOWSOCKS = "shadowsocks"


class TLSConfig(BaseModel):
    enabled: bool = True
    server_name: str | None = None
    insecure: bool = False
    fingerprint: str = "chrome"
    reality_public_key: str | None = None
    reality_short_id: str | None = None
    certificate_pin_sha256: str | None = None


class Endpoint(BaseModel):
    """A single client-visible proxy endpoint."""

    tag: str
    protocol: Protocol
    name: str
    server: str
    port: int = Field(ge=1, le=65535)
    uuid: str | None = None
    password: str | None = None
    flow: str = "xtls-rprx-vision"
    method: str = "2022-blake3-aes-128-gcm"
    tls: TLSConfig = Field(default_factory=TLSConfig)

    @field_validator("tag")
    @classmethod
    def _tag_safe(cls, value: str) -> str:
        if not value or len(value) > 64 or any(ch in value for ch in '"\\\n\r'):
            raise ValueError("endpoint tag is invalid")
        return value

    def to_singbox_outbound(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "type": self._singbox_type(),
            "tag": self.tag,
            "server": self.server,
            "server_port": self.port,
        }
        if self.protocol is Protocol.VLESS_REALITY:
            base.update(
                {
                    "uuid": self.uuid,
                    "flow": self.flow or None,
                    "tls": {
                        "enabled": True,
                        "server_name": self.tls.server_name,
                        "utls": {
                            "enabled": True,
                            "fingerprint": self.tls.fingerprint or "chrome",
                        },
                        "reality": {
                            "enabled": True,
                            "public_key": self.tls.reality_public_key,
                            "short_id": self.tls.reality_short_id or "",
                        },
                    },
                }
            )
        elif self.protocol is Protocol.HYSTERIA2 or self.protocol is Protocol.TROJAN:
            base.update(
                {
                    "password": self.password,
                    "tls": self._tls_block(),
                }
            )
        else:
            base.update(
                {
                    "method": self.method,
                    "password": self.password,
                    "udp_over_tcp": False,
                }
            )
        return {key: value for key, value in base.items() if value is not None}

    def _singbox_type(self) -> str:
        return {
            Protocol.VLESS_REALITY: "vless",
            Protocol.HYSTERIA2: "hysteria2",
            Protocol.TROJAN: "trojan",
            Protocol.SHADOWSOCKS: "shadowsocks",
        }[self.protocol]

    def _tls_block(self) -> dict[str, Any]:
        block: dict[str, Any] = {
            "enabled": True,
            "server_name": self.tls.server_name,
            "insecure": self.tls.insecure,
        }
        if self.tls.certificate_pin_sha256:
            block["certificate_public_key_sha256"] = self.tls.certificate_pin_sha256
        return {key: value for key, value in block.items() if value is not None}

    def to_clash_proxy(self) -> dict[str, Any]:
        common: dict[str, Any] = {
            "name": self.tag,
            "server": self.server,
            "port": self.port,
            "udp": True,
        }
        if self.protocol is Protocol.VLESS_REALITY:
            return {
                **common,
                "type": "vless",
                "uuid": self.uuid,
                "network": "tcp",
                "tls": True,
                "flow": self.flow,
                "servername": self.tls.server_name,
                "client-fingerprint": self.tls.fingerprint or "chrome",
                "reality-opts": {
                    "public-key": self.tls.reality_public_key,
                    "short-id": self.tls.reality_short_id or "",
                },
            }
        if self.protocol is Protocol.HYSTERIA2:
            proxy = {
                **common,
                "type": "hysteria2",
                "password": self.password,
                "sni": self.tls.server_name,
                "skip-cert-verify": self.tls.insecure,
            }
            if self.tls.certificate_pin_sha256:
                proxy["fingerprint"] = self.tls.certificate_pin_sha256
            return proxy
        if self.protocol is Protocol.TROJAN:
            return {
                **common,
                "type": "trojan",
                "password": self.password,
                "sni": self.tls.server_name,
                "skip-cert-verify": self.tls.insecure,
            }
        return {
            **common,
            "type": "ss",
            "cipher": self.method,
            "password": self.password,
            "plugin": "",
        }

    def to_uri(self) -> str:
        query: dict[str, str] = {}
        fragment = quote(self.name or self.tag)
        if self.protocol is Protocol.VLESS_REALITY:
            query = {
                "encryption": "none",
                "security": "reality",
                "sni": self.tls.server_name or "",
                "fp": self.tls.fingerprint or "chrome",
                "pbk": self.tls.reality_public_key or "",
                "sid": self.tls.reality_short_id or "",
                "type": "tcp",
                "flow": self.flow,
            }
            return (
                f"vless://{self.uuid}@{_host(self.server)}:{self.port}?{_query(query)}#{fragment}"
            )
        if self.protocol is Protocol.HYSTERIA2:
            query = {
                "sni": self.tls.server_name or "",
                "insecure": "1" if self.tls.insecure else "0",
            }
            if self.tls.certificate_pin_sha256:
                query["pinSHA256"] = self.tls.certificate_pin_sha256
            return (
                f"hysteria2://{quote(self.password or '')}@{_host(self.server)}:"
                f"{self.port}?{_query(query)}#{fragment}"
            )
        if self.protocol is Protocol.TROJAN:
            query = {
                "security": "tls",
                "sni": self.tls.server_name or "",
                "type": "tcp",
            }
            return (
                f"trojan://{quote(self.password or '')}@{_host(self.server)}:"
                f"{self.port}?{_query(query)}#{fragment}"
            )
        userinfo = (
            base64.urlsafe_b64encode(f"{self.method}:{self.password}".encode()).decode().rstrip("=")
        )
        return f"ss://{userinfo}@{_host(self.server)}:{self.port}#{fragment}"

    @classmethod
    def from_uri(cls, uri: str, tag: str | None = None) -> Endpoint:
        parsed = urlparse(uri.strip())
        scheme = parsed.scheme.lower()
        name = unquote(parsed.fragment) or parsed.hostname or "Imported"
        host = parsed.hostname or ""
        port = parsed.port or 0
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        if scheme == "vless":
            return cls(
                tag=tag or _slug(name),
                protocol=Protocol.VLESS_REALITY,
                name=name,
                server=host,
                port=port,
                uuid=parsed.username,
                flow=query.get("flow", "xtls-rprx-vision"),
                tls=TLSConfig(
                    server_name=query.get("sni") or query.get("host"),
                    reality_public_key=query.get("pbk"),
                    reality_short_id=query.get("sid"),
                    fingerprint=query.get("fp", "chrome"),
                ),
            )
        if scheme in {"hysteria2", "hy2"}:
            return cls(
                tag=tag or _slug(name),
                protocol=Protocol.HYSTERIA2,
                name=name,
                server=host,
                port=port,
                password=unquote(parsed.username or ""),
                tls=TLSConfig(
                    server_name=query.get("sni") or query.get("peer"),
                    insecure=query.get("insecure") in {"1", "true"},
                    certificate_pin_sha256=query.get("pinSHA256"),
                ),
            )
        if scheme == "trojan":
            return cls(
                tag=tag or _slug(name),
                protocol=Protocol.TROJAN,
                name=name,
                server=host,
                port=port,
                password=unquote(parsed.username or ""),
                tls=TLSConfig(
                    server_name=query.get("sni") or query.get("peer"),
                    insecure=query.get("allowInsecure") in {"1", "true"},
                ),
            )
        if scheme == "ss":
            raw = parsed.username or ""
            padded = raw + "=" * (-len(raw) % 4)
            try:
                decoded = base64.urlsafe_b64decode(padded).decode()
            except Exception as exc:
                raise ValueError("invalid shadowsocks URI") from exc
            if ":" not in decoded:
                raise ValueError("invalid shadowsocks URI userinfo")
            method, password = decoded.split(":", 1)
            return cls(
                tag=tag or _slug(name),
                protocol=Protocol.SHADOWSOCKS,
                name=name,
                server=host,
                port=port,
                method=method,
                password=password,
            )
        raise ValueError(f"unsupported proxy URI scheme: {scheme}")


class ProfileDocument(BaseModel):
    """Ostium Profile v1 — the first-class subscription format."""

    format: str = "ostium-profile"
    version: int = PROFILE_FORMAT_VERSION
    name: str
    generated_at: str | None = None
    endpoints: list[Endpoint]
    routing_mode: str = "smart"
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, data: str) -> ProfileDocument:
        payload = json.loads(data)
        if payload.get("format") not in {None, "ostium-profile"}:
            raise ValueError("not an Ostium profile")
        return cls.model_validate(payload)


def _host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _query(values: dict[str, str]) -> str:
    return "&".join(f"{quote(key)}={quote(value)}" for key, value in values.items() if value != "")


def _slug(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")
    return (cleaned or "endpoint")[:64]
