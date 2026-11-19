"""Subscription renderers for Base64 URI, Clash/Mihomo, sing-box and plain URI."""

from __future__ import annotations

import base64
import json

import yaml

from .endpoints import Endpoint


def render_uri_list(endpoints: list[Endpoint]) -> str:
    return "\n".join(endpoint.to_uri() for endpoint in endpoints) + "\n"


def render_base64(endpoints: list[Endpoint]) -> str:
    return base64.b64encode(render_uri_list(endpoints).encode("utf-8")).decode("ascii")


def _proxy_names(endpoints: list[Endpoint]) -> list[str]:
    return [endpoint.name for endpoint in endpoints]


def render_clash(endpoints: list[Endpoint]) -> str:
    names = _proxy_names(endpoints)
    # A subscription should only describe proxies, groups and routing rules.
    # Ports, LAN access, mode, logging, IPv6 and DNS belong to the client;
    # shipping them overrides the user's settings and can make imports fail on
    # clients whose defaults or ports differ.
    config = {
        "proxies": [endpoint.to_clash_proxy() for endpoint in endpoints],
        "proxy-groups": [
            {
                "name": "Ostium",
                "type": "select",
                "proxies": ["Auto", *names],
            },
            {
                "name": "Auto",
                "type": "url-test",
                "url": "https://www.gstatic.com/generate_204",
                "interval": 180,
                "tolerance": 50,
                "proxies": names,
            },
        ],
        # Avoid GEOIP/GEOSITE rules: they require an external MMDB/geosite
        # database. If the client has no database, mihomo refuses to load the
        # profile. DOMAIN-SUFFIX,cn needs no external data.
        "rules": [
            "DOMAIN,localhost,DIRECT",
            "DOMAIN-SUFFIX,local,DIRECT",
            "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
            "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
            "IP-CIDR,100.64.0.0/10,DIRECT,no-resolve",
            "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve",
            "IP-CIDR6,::1/128,DIRECT,no-resolve",
            "DOMAIN-SUFFIX,cn,DIRECT",
            "MATCH,Ostium",
        ],
    }
    return yaml.safe_dump(config, sort_keys=False, allow_unicode=True, default_flow_style=False)


def render_singbox(endpoints: list[Endpoint]) -> str:
    names = _proxy_names(endpoints)
    outbounds: list[dict] = [endpoint.to_singbox_outbound() for endpoint in endpoints]
    outbounds.append(
        {
            "type": "urltest",
            "tag": "Auto",
            "outbounds": names,
            "url": "https://www.gstatic.com/generate_204",
            "interval": "3m",
            "tolerance": 50,
        }
    )
    outbounds.append(
        {
            "type": "selector",
            "tag": "Ostium",
            "outbounds": ["Auto", *names, "direct"],
            "default": "Auto",
        }
    )
    outbounds.append({"type": "direct", "tag": "direct"})
    config = {
        "log": {"level": "info", "timestamp": True},
        # Keep DNS out of the generated profile; sing-box falls back to the
        # system resolver, which is what the client already uses normally.
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": 7890,
            }
        ],
        "outbounds": outbounds,
        "route": {
            "rules": [
                {"action": "sniff"},
                {"protocol": "dns", "action": "hijack-dns"},
                {"ip_is_private": True, "outbound": "direct"},
            ],
            "final": "Ostium",
            "auto_detect_interface": True,
        },
        "experimental": {"cache_file": {"enabled": True}},
    }
    return json.dumps(config, indent=2, ensure_ascii=False) + "\n"


def content_type_for(target: str) -> str:
    return {
        "base64": "text/plain; charset=utf-8",
        "uri": "text/plain; charset=utf-8",
        "clash": "text/yaml; charset=utf-8",
        "singbox": "application/json; charset=utf-8",
    }[target]


def extension_for(target: str) -> str:
    return {"base64": "txt", "uri": "txt", "clash": "yaml", "singbox": "json"}[target]


def render(target: str, endpoints: list[Endpoint]) -> str:
    if target == "base64":
        return render_base64(endpoints)
    if target == "uri":
        return render_uri_list(endpoints)
    if target == "clash":
        return render_clash(endpoints)
    if target == "singbox":
        return render_singbox(endpoints)
    raise ValueError(f"Unknown subscription target: {target}")
