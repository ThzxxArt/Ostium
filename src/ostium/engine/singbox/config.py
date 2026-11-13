"""Deterministic sing-box configuration generation for both roles.

These builders are pure functions: callers load database state and pass plain
dataclasses, which makes golden tests and `sing-box check` validation cheap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ostium.domain.endpoints import Endpoint

LAN_CIDRS = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "127.0.0.0/8",
    "100.64.0.0/10",
    "fc00::/7",
    "fe80::/10",
    "::1/128",
]

TUN_EXCLUDE_CIDRS = [
    *LAN_CIDRS,
    "224.0.0.0/4",
    "240.0.0.0/4",
    "255.255.255.255/32",
    "ff00::/8",
]

SERVER_EGRESS_BLOCK_CIDRS = [
    # IPv4 private, CGNAT and special-use ranges.
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",  # CGNAT / carrier-grade NAT
    "127.0.0.0/8",
    "169.254.0.0/16",  # complete link-local range (cloud metadata lives here)
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",  # multicast
    "240.0.0.0/4",  # reserved
    "255.255.255.255/32",
    # Cloud metadata services (AWS/GCP/Azure/OpenStack/Alibaba).
    "169.254.169.254/32",
    "169.254.170.2/32",
    "169.254.170.23/32",
    "100.100.100.200/32",
    # IPv6 loopback, ULA, link-local and multicast.
    "::1/128",
    "fc00::/7",
    "fe80::/10",
    "ff00::/8",
    # IPv6 cloud metadata endpoints.
    "fd00:ec2::254/128",
    "fe80::a9fe:a9fe/128",
]

# Always blocked, even when private egress is explicitly allowed: an open
# relay must never be usable to send mail.
SERVER_EGRESS_BLOCK_PORTS = [25]

DEFAULT_RULE_SETS = {
    "geosite-cn": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-cn.srs",
    "geoip-cn": "https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-cn.srs",
    "geosite-ads": (
        "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/"
        "geosite-category-ads-all.srs"
    ),
}

# The built-in smart preset must work offline on first start.  It therefore uses
# deterministic domain suffixes rather than downloading remote rule-sets during
# core startup; advanced users can add GeoIP/GeoSite rule-sets explicitly.
CN_DOMAIN_SUFFIXES = [
    ".cn",
    "baidu.com",
    "bdstatic.com",
    "qq.com",
    "qpic.cn",
    "gtimg.cn",
    "wechat.com",
    "weixin.qq.com",
    "taobao.com",
    "tmall.com",
    "alicdn.com",
    "alipay.com",
    "aliyun.com",
    "jd.com",
    "360buyimg.com",
    "bilibili.com",
    "hdslb.com",
    "douyin.com",
    "bytedance.com",
    "toutiao.com",
    "iqiyi.com",
    "youku.com",
    "weibo.com",
    "sina.com.cn",
    "sohu.com",
    "163.com",
    "126.net",
    "netease.com",
    "xiaomi.com",
    "mi.com",
    "huawei.com",
    "honor.com",
    "oppo.com",
    "vivo.com",
    "meituan.com",
    "dianping.com",
    "ctrip.com",
    "12306.cn",
    "gov.cn",
    "edu.cn",
]

AD_DOMAIN_SUFFIXES = [
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "adnxs.com",
    "taboola.com",
    "outbrain.com",
    "criteo.com",
    "adsrvr.org",
]


@dataclass(frozen=True)
class UserCredential:
    name: str
    uuid: str
    password: str
    ss_password: str


@dataclass
class RealitySpec:
    private_key: str
    short_id: str
    server_name: str = "www.apple.com"
    handshake_server: str | None = None
    handshake_port: int = 443


@dataclass
class CertificateSpec:
    cert_path: str
    key_path: str


@dataclass
class ServerInbound:
    kind: str
    enabled: bool
    listen: str = "0.0.0.0"
    port: int = 443
    reality: RealitySpec | None = None
    certificate: CertificateSpec | None = None
    obfs_password: str | None = None
    ss_server_key: str | None = None


@dataclass
class ServerConfigSpec:
    inbounds: list[ServerInbound]
    users: list[UserCredential]
    clash_secret: str
    v2ray_listen: str = "127.0.0.1:19091"
    clash_listen: str = "127.0.0.1:19090"
    log_level: str = "info"
    block_private_egress: bool = True
    enable_v2ray_api: bool = True


@dataclass
class ClientTunSpec:
    enabled: bool = False
    interface_name: str = "ostium0"
    mtu: int = 1500
    stack: str = "gvisor"
    ipv6: bool = True
    auto_route: bool = True
    strict_route: bool = True
    dns_mode: str = "hijack"


@dataclass
class ClientConfigSpec:
    endpoints: list[Endpoint]
    mixed_port: int = 7890
    allow_lan: bool = False
    mode: str = "mixed"
    selected: str | None = None
    routing_mode: str = "smart"
    rules: list[dict[str, Any]] = field(default_factory=list)
    rule_sets: list[dict[str, Any]] = field(default_factory=list)
    tun: ClientTunSpec = field(default_factory=ClientTunSpec)
    clash_secret: str = ""
    clash_listen: str = "127.0.0.1:19090"
    log_level: str = "info"
    ipv6: bool = True
    dns_remote: str = "https://1.1.1.1/dns-query"
    dns_local: str = "223.5.5.5"


def build_server_config(
    spec: ServerConfigSpec, *, include_v2ray_api: bool | None = None
) -> dict[str, Any]:
    inbounds: list[dict[str, Any]] = []
    inbounds_tags: list[str] = []
    for inbound in spec.inbounds:
        if not inbound.enabled:
            continue
        entry = _server_inbound(inbound, spec.users)
        if entry is not None:
            inbounds.append(entry)
            inbounds_tags.append(str(entry["tag"]))

    route_rules: list[dict[str, Any]] = []
    if spec.block_private_egress:
        route_rules.append({"action": "reject", "ip_cidr": SERVER_EGRESS_BLOCK_CIDRS})
    route_rules.append({"action": "reject", "port": SERVER_EGRESS_BLOCK_PORTS})

    config: dict[str, Any] = {
        "log": {"level": spec.log_level, "timestamp": True},
        "dns": {
            "servers": [{"type": "udp", "tag": "local", "server": "223.5.5.5"}],
            "final": "local",
        },
        "inbounds": inbounds,
        "outbounds": [
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
        ],
        "route": {
            "rules": route_rules,
            "final": "direct",
            "auto_detect_interface": True,
        },
        "experimental": {
            "clash_api": {
                "external_controller": spec.clash_listen,
                "secret": spec.clash_secret,
                "default_mode": "rule",
            }
        },
    }
    v2ray_enabled = spec.enable_v2ray_api if include_v2ray_api is None else include_v2ray_api
    if v2ray_enabled:
        config["experimental"]["v2ray_api"] = {
            "listen": spec.v2ray_listen,
            "stats": {
                "enabled": True,
                "inbounds": inbounds_tags,
                "users": [user.name for user in spec.users],
            },
        }
    return config


def _server_inbound(inbound: ServerInbound, users: list[UserCredential]) -> dict[str, Any] | None:
    base: dict[str, Any] = {
        "type": inbound.kind,
        "tag": f"{inbound.kind}-in",
        "listen": inbound.listen,
        "listen_port": inbound.port,
    }
    if inbound.kind == "vless":
        if not inbound.reality:
            return None
        base["users"] = [
            {"name": user.name, "uuid": user.uuid, "flow": "xtls-rprx-vision"} for user in users
        ]
        base["tls"] = {
            "enabled": True,
            "server_name": inbound.reality.server_name,
            "reality": {
                "enabled": True,
                "handshake": {
                    "server": inbound.reality.handshake_server or inbound.reality.server_name,
                    "server_port": inbound.reality.handshake_port,
                },
                "private_key": inbound.reality.private_key,
                "short_id": [inbound.reality.short_id],
            },
        }
        return base
    if inbound.kind == "hysteria2":
        if not inbound.certificate:
            return None
        base["users"] = [{"name": user.name, "password": user.password} for user in users]
        base["tls"] = {
            "enabled": True,
            "certificate_path": inbound.certificate.cert_path,
            "key_path": inbound.certificate.key_path,
        }
        base["masquerade"] = {
            "type": "string",
            "status_code": 200,
            "headers": {"Content-Type": "text/html; charset=utf-8"},
            "content": (
                "<!doctype html><html><head><title>Welcome</title></head>"
                "<body><h1>It works!</h1></body></html>"
            ),
        }
        if inbound.obfs_password:
            base["obfs"] = {"type": "salamander", "password": inbound.obfs_password}
        return base
    if inbound.kind == "trojan":
        if not inbound.certificate:
            return None
        base["users"] = [{"name": user.name, "password": user.password} for user in users]
        base["tls"] = {
            "enabled": True,
            "certificate_path": inbound.certificate.cert_path,
            "key_path": inbound.certificate.key_path,
        }
        return base
    if inbound.kind == "shadowsocks":
        base["method"] = "2022-blake3-aes-128-gcm"
        base["password"] = inbound.ss_server_key or (users[0].ss_password if users else "")
        base["users"] = [{"name": user.name, "password": user.ss_password} for user in users]
        return base
    return None


def build_client_config(
    spec: ClientConfigSpec, *, tun_interface: str | None = None
) -> dict[str, Any]:
    if not spec.endpoints:
        raise ValueError("a client profile needs at least one endpoint")

    outbounds: list[dict[str, Any]] = [
        endpoint.to_singbox_outbound() for endpoint in spec.endpoints
    ]
    tags = [endpoint.tag for endpoint in spec.endpoints]
    tun_enabled = spec.tun.enabled or spec.mode == "tun"

    if len(tags) > 1:
        outbounds.append(
            {
                "type": "urltest",
                "tag": "auto",
                "outbounds": tags,
                "url": "https://www.gstatic.com/generate_204",
                "interval": "180s",
                "tolerance": 50,
            }
        )
        selector_choices = ["auto", *tags]
        default = spec.selected or "auto"
    else:
        selector_choices = tags
        default = spec.selected or tags[0]

    outbounds.append(
        {
            "type": "selector",
            "tag": "proxy",
            "outbounds": selector_choices,
            "default": default,
            "interrupt_exist_connections": True,
        }
    )
    outbounds.append({"type": "direct", "tag": "direct"})

    inbounds: list[dict[str, Any]] = []
    if tun_enabled:
        interface = tun_interface or spec.tun.interface_name
        address = ["172.19.0.1/30"]
        if spec.tun.ipv6 and spec.ipv6:
            address.append("fdfe:dcba:9876::1/126")
        inbounds.append(
            {
                "type": "tun",
                "tag": "tun-in",
                "interface_name": interface,
                "address": address,
                "mtu": spec.tun.mtu,
                "stack": spec.tun.stack,
                "dns_mode": spec.tun.dns_mode,
                "auto_route": spec.tun.auto_route,
                "strict_route": spec.tun.strict_route,
                "route_exclude_address": TUN_EXCLUDE_CIDRS,
            }
        )
    if not tun_enabled or spec.mode != "tun":
        inbounds.append(
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "0.0.0.0" if spec.allow_lan else "127.0.0.1",
                "listen_port": spec.mixed_port,
            }
        )

    route_rules = _client_route_rules(spec, tun_enabled)
    rule_sets = _rule_sets(spec)
    dns = _client_dns(spec, tun_enabled)

    config: dict[str, Any] = {
        "log": {"level": spec.log_level, "timestamp": True},
        "dns": dns,
        "inbounds": inbounds,
        "outbounds": outbounds,
        "route": {
            "rules": route_rules,
            "rule_set": rule_sets,
            "final": "proxy" if spec.routing_mode != "direct" else "direct",
            "auto_detect_interface": True,
            "default_domain_resolver": {"server": "local"},
        },
        "experimental": {
            "clash_api": {
                "external_controller": spec.clash_listen,
                "secret": spec.clash_secret or "ostium-local",
            },
            "cache_file": {"enabled": True, "store_fakeip": True},
        },
    }
    return config


def _client_route_rules(spec: ClientConfigSpec, tun_enabled: bool) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    if tun_enabled:
        rules.append({"action": "sniff"})
        rules.append({"protocol": "dns", "action": "hijack-dns"})
    rules.append({"ip_is_private": True, "outbound": "direct"})
    if spec.routing_mode == "smart":
        rules.append({"domain_suffix": CN_DOMAIN_SUFFIXES, "outbound": "direct"})
        rules.append({"domain_suffix": AD_DOMAIN_SUFFIXES, "action": "reject"})
    for rule in spec.rules:
        action = rule.get("action", "proxy")
        mapped: dict[str, Any] = {
            key: value
            for key, value in rule.items()
            if key
            in {
                "domain",
                "domain_suffix",
                "domain_keyword",
                "domain_regex",
                "ip_cidr",
                "port",
                "source_port",
                "process_name",
                "rule_set",
                "network",
                "protocol",
            }
        }
        if action == "block":
            mapped["action"] = "reject"
        else:
            mapped["outbound"] = "proxy" if action == "proxy" else "direct"
        rules.append(mapped)
    return rules


def _rule_sets(spec: ClientConfigSpec) -> list[dict[str, Any]]:
    defined: dict[str, dict[str, Any]] = {}
    for entry in spec.rule_sets:
        tag = str(entry.get("tag") or entry.get("name") or "custom")
        if entry.get("path"):
            defined[tag] = {"type": "local", "tag": tag, "format": "binary", "path": entry["path"]}
        elif entry.get("url"):
            defined[tag] = {
                "type": "remote",
                "tag": tag,
                "format": entry.get("format", "binary"),
                "url": entry["url"],
                "update_interval": entry.get("update_interval", "7d"),
            }
    return list(defined.values())


def _client_dns(spec: ClientConfigSpec, tun_enabled: bool) -> dict[str, Any]:
    if spec.routing_mode == "direct":
        # Direct mode must not send DNS queries through a proxy outbound that
        # is not used for traffic; use the local resolver only.
        return {
            "servers": [{"type": "udp", "tag": "local", "server": spec.dns_local}],
            "rules": [],
            "final": "local",
        }
    servers: list[dict[str, Any]] = [
        {
            "type": "https",
            "tag": "remote",
            "server": spec.dns_remote.removeprefix("https://").split("/")[0],
            "detour": "proxy",
        },
        {"type": "udp", "tag": "local", "server": spec.dns_local},
    ]
    rules: list[dict[str, Any]] = []
    if tun_enabled:
        servers.append(
            {
                "type": "fakeip",
                "tag": "fakeip",
                "inet4_range": "198.18.0.0/15",
                "inet6_range": "fc00::/18",
            }
        )
        rules.append({"query_type": ["A", "AAAA"], "server": "fakeip"})
    if spec.routing_mode == "smart":
        rules.append({"domain_suffix": [".cn"], "server": "local"})
    return {"servers": servers, "rules": rules, "final": "remote"}


def config_digest(config: dict[str, Any]) -> str:
    """Canonical SHA-256 used to bind a core apply request to its payload."""

    import hashlib
    import json

    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def namespace_endpoint_tags(
    groups: list[tuple[str, list[Endpoint]]],
) -> tuple[list[Endpoint], dict[tuple[str, str], str]]:
    """Make endpoint tags unique across profiles without renaming unique ones.

    Returns the flattened endpoints plus a ``(profile_name, original_tag) ->
    effective_tag`` mapping so persisted selections keep working.
    """

    counts: dict[str, int] = {}
    for _profile, endpoints in groups:
        for endpoint in endpoints:
            counts[endpoint.tag] = counts.get(endpoint.tag, 0) + 1
    flattened: list[Endpoint] = []
    mapping: dict[tuple[str, str], str] = {}
    for profile_name, endpoints in groups:
        for endpoint in endpoints:
            effective = endpoint.tag
            if counts.get(endpoint.tag, 0) > 1:
                prefix = _tag_slug(profile_name)
                effective = f"{prefix}-{endpoint.tag}"[:64]
                candidate = effective
                suffix = 2
                while any(item.tag == candidate for item in flattened):
                    candidate = f"{effective[:58]}-{suffix}"
                    suffix += 1
                effective = candidate
            mapping[(profile_name, endpoint.tag)] = effective
            flattened.append(
                endpoint
                if effective == endpoint.tag
                else endpoint.model_copy(update={"tag": effective})
            )
    return flattened, mapping


def _tag_slug(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")
    return (cleaned or "profile")[:24]
