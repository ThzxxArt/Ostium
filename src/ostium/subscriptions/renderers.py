"""Subscription renderers for Base64 URI, Clash/Mihomo, sing-box and plain URI."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

import yaml

from .endpoints import Endpoint


@dataclass(frozen=True, slots=True)
class ProfileOptions:
    """Policy for generated client profiles.

    The defaults are intentionally client-owned: no DNS override, no client
    ports/global settings, no external GeoIP database. Alternative values are
    useful for tests and for future opt-in profiles, without changing the
    default subscription behavior.
    """

    dns_mode: str = "client"  # client | system
    routing: str = "cn-direct"  # cn-direct | global
    include_client_settings: bool = False
    include_geodata: bool = False


DEFAULT_PROFILE = ProfileOptions()


def render_uri_list(endpoints: list[Endpoint]) -> str:
    return "\n".join(endpoint.to_uri() for endpoint in endpoints) + "\n"


def render_base64(endpoints: list[Endpoint]) -> str:
    return base64.b64encode(render_uri_list(endpoints).encode("utf-8")).decode("ascii")


def _proxy_names(endpoints: list[Endpoint]) -> list[str]:
    return [endpoint.name for endpoint in endpoints]


def _clash_dns() -> dict:
    """Reachable bootstrap DNS, only used when explicitly opted in."""

    return {
        "enable": True,
        "ipv6": False,
        "enhanced-mode": "fake-ip",
        "fake-ip-range": "198.18.0.1/16",
        "default-nameserver": ["223.5.5.5", "119.29.29.29"],
        "nameserver": ["223.5.5.5", "119.29.29.29"],
        "proxy-server-nameserver": ["223.5.5.5", "119.29.29.29"],
    }


def render_clash(endpoints: list[Endpoint], options: ProfileOptions | None = None) -> str:
    options = options or DEFAULT_PROFILE
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
        # Avoid GEOIP/GEOSITE rules by default: they require an external
        # MMDB/geosite database. If the client has no database, mihomo refuses
        # to load the profile. DOMAIN-SUFFIX,cn needs no external data.
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
            "MATCH,Ostium",
        ],
    }
    if options.routing == "cn-direct":
        config["rules"].insert(-1, "DOMAIN-SUFFIX,cn,DIRECT")
    if options.include_geodata:
        config["rules"].insert(-1, "GEOIP,CN,DIRECT,no-resolve")
    if options.dns_mode == "system":
        config["dns"] = _clash_dns()
    if options.include_client_settings:
        config = {
            "mixed-port": 7890,
            "allow-lan": False,
            "bind-address": "127.0.0.1",
            "mode": "rule",
            "log-level": "info",
            "ipv6": False,
            **config,
        }
    return yaml.safe_dump(config, sort_keys=False, allow_unicode=True, default_flow_style=False)


def render_singbox(endpoints: list[Endpoint], options: ProfileOptions | None = None) -> str:
    options = options or DEFAULT_PROFILE
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
        # Keep DNS out of the generated profile by default; sing-box falls
        # back to the system resolver, which is what the client already uses.
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
    if options.routing == "cn-direct":
        config["route"]["rules"].append({"domain_suffix": ["cn"], "outbound": "direct"})
    if options.dns_mode == "system":
        config["dns"] = {
            "servers": [{"type": "udp", "tag": "local", "server": "223.5.5.5"}],
            "final": "local",
            "strategy": "ipv4_only",
        }
        config["route"]["default_domain_resolver"] = "local"
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


def render(target: str, endpoints: list[Endpoint], options: ProfileOptions | None = None) -> str:
    if target == "base64":
        return render_base64(endpoints)
    if target == "uri":
        return render_uri_list(endpoints)
    if target == "clash":
        return render_clash(endpoints, options)
    if target == "singbox":
        return render_singbox(endpoints, options)
    raise ValueError(f"Unknown subscription target: {target}")
