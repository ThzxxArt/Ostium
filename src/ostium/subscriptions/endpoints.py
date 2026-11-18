"""Protocol endpoints derived from enabled inbounds and one proxy user."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from urllib.parse import quote, urlencode

from ostium.proxy.models import ProxyUser


def _host_for_url(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _b64url(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


@dataclass(slots=True)
class Endpoint:
    protocol: str
    label: str
    server: str
    port: int
    name: str
    uuid: str | None = None
    password: str | None = None
    method: str | None = None
    server_key: str | None = None
    user_key: str | None = None
    sni: str | None = None
    reality_public_key: str | None = None
    reality_short_id: str | None = None
    flow: str | None = None
    obfs: str | None = None
    obfs_password: str | None = None
    cert_fingerprint: str | None = None
    cert_fingerprint_b64: str | None = None
    cert_public_key_sha256: str | None = None
    self_signed: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def ss_password(self) -> str | None:
        if self.server_key and self.user_key:
            return f"{self.server_key}:{self.user_key}"
        return None

    def to_uri(self) -> str:
        host = _host_for_url(self.server)
        fragment = quote(self.name, safe="")
        if self.protocol == "vless":
            params = {
                "encryption": "none",
                "security": "reality",
                "sni": self.sni or self.server,
                "fp": "chrome",
                "pbk": self.reality_public_key or "",
                "sid": self.reality_short_id or "",
                "type": "tcp",
                "flow": self.flow or "xtls-rprx-vision",
            }
            return f"vless://{self.uuid}@{host}:{self.port}?{urlencode(params, quote_via=quote)}#{fragment}"
        if self.protocol == "hysteria2":
            params = {"sni": self.sni or self.server, "insecure": "0"}
            if self.obfs and self.obfs_password:
                params["obfs"] = self.obfs
                params["obfs-password"] = self.obfs_password
            if self.cert_fingerprint and self.self_signed:
                params["pinSHA256"] = self.cert_fingerprint
            userinfo = quote(self.password or "", safe="")
            return f"hysteria2://{userinfo}@{host}:{self.port}?{urlencode(params, quote_via=quote)}#{fragment}"
        if self.protocol == "trojan":
            params = {"security": "tls", "sni": self.sni or self.server, "type": "tcp", "allowInsecure": "0"}
            if self.cert_fingerprint_b64 and self.self_signed:
                params["pcs"] = self.cert_fingerprint_b64
            userinfo = quote(self.password or "", safe="")
            return f"trojan://{userinfo}@{host}:{self.port}?{urlencode(params, quote_via=quote)}#{fragment}"
        if self.protocol == "shadowsocks":
            if (self.method or "").startswith("2022-"):
                # SIP022: Shadowsocks 2022 userinfo is not base64 encoded.
                userinfo = f"{quote(self.method or '', safe='')}:{quote(self.ss_password or '', safe='')}"
            else:
                userinfo = _b64url(f"{self.method}:{self.ss_password}")
            return f"ss://{userinfo}@{host}:{self.port}#{fragment}"
        raise ValueError(f"Unsupported protocol: {self.protocol}")

    def to_clash_proxy(self) -> dict:
        common = {"name": self.name, "server": self.server, "port": self.port, "udp": True}
        if self.protocol == "vless":
            proxy = {
                **common,
                "type": "vless",
                "uuid": self.uuid,
                "network": "tcp",
                "tls": True,
                "flow": self.flow or "xtls-rprx-vision",
                "servername": self.sni or self.server,
                "client-fingerprint": "chrome",
                "reality-opts": {
                    "public-key": self.reality_public_key,
                    "short-id": self.reality_short_id or "",
                },
            }
            return proxy
        if self.protocol == "hysteria2":
            proxy = {
                **common,
                "type": "hysteria2",
                "password": self.password,
                "sni": self.sni or self.server,
                "skip-cert-verify": False,
            }
            if self.obfs and self.obfs_password:
                proxy["obfs"] = self.obfs
                proxy["obfs-password"] = self.obfs_password
            if self.cert_fingerprint and self.self_signed:
                proxy["fingerprint"] = self.cert_fingerprint
            return proxy
        if self.protocol == "trojan":
            proxy = {
                **common,
                "type": "trojan",
                "password": self.password,
                "sni": self.sni or self.server,
                "skip-cert-verify": False,
            }
            if self.cert_fingerprint and self.self_signed:
                proxy["fingerprint"] = self.cert_fingerprint
            return proxy
        if self.protocol == "shadowsocks":
            return {
                **common,
                "type": "ss",
                "cipher": self.method,
                "password": self.ss_password,
                "udp": False,
            }
        raise ValueError(f"Unsupported protocol: {self.protocol}")

    def to_singbox_outbound(self) -> dict:
        if self.protocol == "vless":
            return {
                "type": "vless",
                "tag": self.name,
                "server": self.server,
                "server_port": self.port,
                "uuid": self.uuid,
                "flow": self.flow or "xtls-rprx-vision",
                "tls": {
                    "enabled": True,
                    "server_name": self.sni or self.server,
                    "utls": {"enabled": True, "fingerprint": "chrome"},
                    "reality": {
                        "enabled": True,
                        "public_key": self.reality_public_key,
                        "short_id": self.reality_short_id or "",
                    },
                },
            }
        if self.protocol == "hysteria2":
            tls = {"enabled": True, "server_name": self.sni or self.server}
            if self.self_signed and self.cert_public_key_sha256:
                tls["certificate_public_key_sha256"] = self.cert_public_key_sha256
            outbound = {
                "type": "hysteria2",
                "tag": self.name,
                "server": self.server,
                "server_port": self.port,
                "password": self.password,
                "tls": tls,
            }
            if self.obfs and self.obfs_password:
                outbound["obfs"] = {"type": self.obfs, "password": self.obfs_password}
            return outbound
        if self.protocol == "trojan":
            tls = {"enabled": True, "server_name": self.sni or self.server}
            if self.self_signed and self.cert_public_key_sha256:
                tls["certificate_public_key_sha256"] = self.cert_public_key_sha256
            return {
                "type": "trojan",
                "tag": self.name,
                "server": self.server,
                "server_port": self.port,
                "password": self.password,
                "tls": tls,
            }
        if self.protocol == "shadowsocks":
            return {
                "type": "shadowsocks",
                "tag": self.name,
                "server": self.server,
                "server_port": self.port,
                "method": self.method,
                "password": self.ss_password,
            }
        raise ValueError(f"Unsupported protocol: {self.protocol}")


def build_endpoints(user: ProxyUser, host: str) -> list[Endpoint]:
    """Build the ordered endpoint list for a user.

    Disabled, incomplete and certificate-less inbounds are skipped silently;
    the subscription endpoint rejects a user with no usable endpoint.
    """

    from ostium.proxy.models import Inbound

    endpoints: list[Endpoint] = []
    host = host.strip().strip("[]")
    for inbound in Inbound.objects.filter(enabled=True).select_related("certificate").order_by("kind"):
        params = inbound.params
        label = inbound.short_label
        name = f"{host} · {label}"
        certificate = inbound.certificate
        if inbound.needs_certificate:
            if certificate is None or not certificate.is_ready:
                continue
            from ostium.certificates.services import certificate_pins

            sni = certificate.domain
            fingerprint = certificate.fingerprint_sha256
            fingerprint_b64, public_key_pin = certificate_pins(certificate)
            self_signed = certificate.source == "self_signed"
        else:
            sni = None
            fingerprint = None
            fingerprint_b64 = None
            public_key_pin = None
            self_signed = False

        if inbound.kind == Inbound.Kind.VLESS:
            if not params.get("public_key"):
                continue
            endpoints.append(
                Endpoint(
                    protocol="vless",
                    label=label,
                    server=host,
                    port=inbound.port,
                    name=name,
                    uuid=str(user.uuid),
                    sni=params.get("server_name") or "www.microsoft.com",
                    reality_public_key=params.get("public_key"),
                    reality_short_id=params.get("short_id"),
                    flow="xtls-rprx-vision",
                )
            )
        elif inbound.kind == Inbound.Kind.HYSTERIA2:
            endpoints.append(
                Endpoint(
                    protocol="hysteria2",
                    label=label,
                    server=host,
                    port=inbound.port,
                    name=name,
                    password=user.password,
                    sni=sni,
                    obfs="salamander" if params.get("obfs_password") else None,
                    obfs_password=params.get("obfs_password"),
                    cert_fingerprint=fingerprint,
                    cert_fingerprint_b64=fingerprint_b64,
                    cert_public_key_sha256=public_key_pin,
                    self_signed=self_signed,
                )
            )
        elif inbound.kind == Inbound.Kind.TROJAN:
            endpoints.append(
                Endpoint(
                    protocol="trojan",
                    label=label,
                    server=host,
                    port=inbound.port,
                    name=name,
                    password=user.password,
                    sni=sni,
                    cert_fingerprint=fingerprint,
                    cert_fingerprint_b64=fingerprint_b64,
                    cert_public_key_sha256=public_key_pin,
                    self_signed=self_signed,
                )
            )
        elif inbound.kind == Inbound.Kind.SHADOWSOCKS:
            if not params.get("server_key"):
                continue
            endpoints.append(
                Endpoint(
                    protocol="shadowsocks",
                    label=label,
                    server=host,
                    port=inbound.port,
                    name=name,
                    method=params.get("method"),
                    server_key=params.get("server_key"),
                    user_key=user.ss_password,
                )
            )
    order = {"vless": 0, "hysteria2": 1, "trojan": 2, "shadowsocks": 3}
    endpoints.sort(key=lambda item: order[item.protocol])
    return endpoints
