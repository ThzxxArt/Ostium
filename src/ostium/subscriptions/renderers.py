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
    config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "bind-address": "127.0.0.1",
        "mode": "rule",
        "log-level": "info",
        "ipv6": False,
        "dns": {
            "enable": True,
            "ipv6": False,
            "enhanced-mode": "fake-ip",
            "fake-ip-range": "198.18.0.1/16",
            "fake-ip-filter": ["*.lan", "*.local", "localhost.ptlogin2.qq.com"],
            "default-nameserver": ["223.5.5.5", "1.1.1.1"],
            "nameserver": ["https://1.1.1.1/dns-query", "https://8.8.8.8/dns-query"],
            "proxy-server-nameserver": ["https://1.1.1.1/dns-query"],
            "fallback-filter": {"geoip": True, "geoip-code": "CN"},
        },
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
        "rules": [
            "DOMAIN-SUFFIX,local,DIRECT",
            "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
            "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
            "IP-CIDR,100.64.0.0/10,DIRECT,no-resolve",
            "IP-CIDR,169.254.0.0/16,DIRECT,no-resolve",
            "IP-CIDR6,::1/128,DIRECT,no-resolve",
            "GEOIP,CN,DIRECT,no-resolve",
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
        "dns": {
            "servers": [
                {"type": "https", "tag": "doh", "server": "1.1.1.1", "path": "/dns-query"},
                {"type": "udp", "tag": "local", "server": "1.1.1.1"},
            ],
            "final": "doh",
            "strategy": "ipv4_only",
        },
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
            "default_domain_resolver": "doh",
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
