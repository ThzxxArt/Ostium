"""Subscription rendering: Ostium JSON, Base64, Clash Meta and sing-box JSON."""

from __future__ import annotations

import base64
import io
import json
from typing import Any

import segno
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.config import Settings
from ostium.domain.endpoints import Endpoint, ProfileDocument
from ostium.services.crypto import SecretStore
from ostium.services.users import (
    UserError,
    endpoints_for_user,
    server_hostname,
    status_of,
)
from ostium.util.time import iso, utcnow


class SubscriptionInactive(UserError):
    def __init__(self) -> None:
        super().__init__("subscription is not active", "subscription_inactive", 403)


async def build_endpoints(
    session: AsyncSession,
    store: SecretStore,
    user: Any,
    *,
    settings: Settings | None = None,
) -> list[Endpoint]:
    if status_of(user) != "online" and status_of(user) != "active":
        raise SubscriptionInactive()
    host = await server_hostname(session)
    return await endpoints_for_user(session, store, user, server_host=host, settings=settings)


async def render_subscription(
    session: AsyncSession,
    store: SecretStore,
    user: Any,
    fmt: str,
    *,
    settings: Settings | None = None,
) -> tuple[str, str]:
    endpoints = await build_endpoints(session, store, user, settings=settings)
    if not endpoints:
        raise SubscriptionInactive()
    if fmt in {"ostium", "json"}:
        document = ProfileDocument(
            name=user.name,
            generated_at=iso(utcnow()),
            endpoints=endpoints,
            metadata={"user": user.name, "source": "ostium"},
        )
        return document.to_json(), "application/json; charset=utf-8"
    if fmt == "base64":
        payload = "\n".join(endpoint.to_uri() for endpoint in endpoints)
        encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
        return encoded, "text/plain; charset=utf-8"
    if fmt == "clash":
        return _render_clash(user.name, endpoints), "text/yaml; charset=utf-8"
    if fmt in {"singbox", "sing-box"}:
        outbounds: list[dict[str, Any]] = [endpoint.to_singbox_outbound() for endpoint in endpoints]
        tags = [endpoint.tag for endpoint in endpoints]
        if len(tags) > 1:
            outbounds.append(
                {
                    "type": "selector",
                    "tag": "proxy",
                    "outbounds": tags,
                    "default": tags[0],
                }
            )
        return json.dumps(
            {"outbounds": outbounds}, indent=2, ensure_ascii=False
        ), "application/json; charset=utf-8"
    raise UserError(f"unknown subscription format: {fmt}", "bad_format", 400)


def _render_clash(name: str, endpoints: list[Endpoint]) -> str:
    proxies = [endpoint.to_clash_proxy() for endpoint in endpoints]
    tags = [endpoint.tag for endpoint in endpoints]
    document = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        # A system proxy cannot capture QUIC, and IPv6 often bypasses a
        # mixed-port listener.  Keep both off by default so browsers fall back
        # to proxied TCP instead of racing a direct UDP/QUIC path.
        "ipv6": False,
        # Without a fake-IP resolver Clash uses the system DNS answer.  In a
        # polluted network Google/YouTube/Hugging Face can resolve to a
        # mainland IP, match GEOIP,CN and be sent DIRECT even though the proxy
        # is healthy.  Fake-IP keeps the domain name on the proxy path; an
        # encrypted domestic resolver only supplies the synthetic address.
        "dns": {
            "enable": True,
            "ipv6": False,
            "enhanced-mode": "fake-ip",
            "fake-ip-range": "198.18.0.1/16",
            "fake-ip-filter": ["*.lan", "*.local", "localhost.ptlogin2.qq.com"],
            # Clash needs literal bootstrap resolvers here; use the same
            # trusted public resolvers as the server.  Do not reintroduce
            # 223.5.5.5: it returned polluted answers on the deployment
            # network.
            "default-nameserver": ["1.1.1.1", "8.8.8.8"],
            "nameserver": [
                "https://1.1.1.1/dns-query",
                "https://8.8.8.8/dns-query",
            ],
            "fallback": [
                "https://1.1.1.1/dns-query",
                "https://8.8.8.8/dns-query",
            ],
            "fallback-filter": {
                "geoip": True,
                "geoip-code": "CN",
                "ipcidr": ["240.0.0.0/4"],
            },
        },
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "Ostium",
                "type": "select",
                "proxies": tags,
            }
        ],
        "rules": [
            "DOMAIN-SUFFIX,local,DIRECT",
            "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
            "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
            # Fake-IP domains never match GEOIP; this rule only handles
            # literal/direct IP connections.  Do not resolve here, otherwise
            # a poisoned A record would recreate the original DIRECT bug.
            "DOMAIN-SUFFIX,cn,DIRECT",
            "GEOIP,CN,DIRECT,no-resolve",
            "MATCH,Ostium",
        ],
    }
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def qr_svg(data: str) -> str:
    buffer = io.BytesIO()
    segno.make(data, error="m").save(
        buffer, kind="svg", scale=5, border=2, dark="#0b1220", light="#ffffff"
    )
    return buffer.getvalue().decode("utf-8")


async def subscription_payload(
    session: AsyncSession,
    store: SecretStore,
    user: Any,
    *,
    base_url: str,
    token: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    endpoints = await endpoints_for_user(
        session,
        store,
        user,
        server_host=await server_hostname(session),
        settings=settings,
    )
    formats = {
        "ostium": "Ostium Profile v1",
        "base64": "Base64 URI list",
        "clash": "Clash Meta YAML",
        "singbox": "sing-box outbounds",
    }
    urls = {key: f"{base_url.rstrip('/')}/sub/{token}?format={key}" for key in formats}
    return {
        "user": user.name,
        "formats": [{"id": key, "name": label, "url": urls[key]} for key, label in formats.items()],
        "links": [endpoint.to_uri() for endpoint in endpoints],
        "qr_svg": qr_svg(urls["ostium"]),
        "expires_at": iso(user.expires_at),
        "quota_bytes": user.quota_bytes,
        "used_bytes": user.used_bytes,
    }
