"""Deterministic sing-box configuration generation for both roles.

These builders are pure functions: callers load database state and pass plain
dataclasses, which makes golden tests and `sing-box check` validation cheap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ostium.domain.endpoints import Endpoint
from ostium.engine.dns import DEFAULT_DOH_URL, DEFAULT_UDP_SERVER, doh_host_and_path

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

# Bumped whenever the generated configuration embeds a new security policy
# (for example the 0.1.1 server egress block list).  The core refuses to start a
# server last-good file that was generated under an older policy; the control
# plane regenerates and applies the current configuration instead of silently
# running stale rules after an upgrade.
CONFIG_POLICY_VERSION = 3

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


@dataclass(frozen=True)
class ServerDnsSpec:
    """The one DNS server the generated configuration actually uses.

    ``sing-box`` resolves through a single ``dns.final`` server.  Listing two
    UDP servers and expecting failover was a no-op: the second entry was never
    referenced.  The control plane therefore selects one mode up front.
    """

    mode: str = "udp"
    doh_url: str = DEFAULT_DOH_URL


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
    dns: ServerDnsSpec = field(default_factory=ServerDnsSpec)


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
    dns_local: str = "local"
    # Absolute path for sing-box's cache file.  Without it sing-box writes
    # ``cache.db`` into its working directory, which is read-only for the
    # packaged systemd/launchd clients (and polluted for manual runs).
    cache_path: str | None = None


def _server_dns_server(spec: ServerDnsSpec) -> dict[str, Any]:
    mode = spec.mode.strip().lower()
    if mode == "doh":
        host, path, tls_name = doh_host_and_path(spec.doh_url or DEFAULT_DOH_URL)
        entry: dict[str, Any] = {
            "type": "https",
            "tag": "local",
            "server": host,
            "path": path,
        }
        # ``detour: direct`` is fatal in sing-box 1.14.x because the direct
        # outbound is empty; omitting it uses the default route.
        if tls_name:
            entry["tls"] = {"server_name": tls_name}
        return entry
    return {"type": "udp", "tag": "local", "server": DEFAULT_UDP_SERVER}


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
            # Exactly one resolver is generated.  Before 0.1.11 a second UDP
            # entry existed but ``dns.final`` only referenced the first, so it
            # never participated in resolution.  DoH is preferred because
            # UDP/53 was observed returning polluted answers; UDP remains an
            # explicit operator choice and the ``auto`` fallback.
            "servers": [_server_dns_server(spec.dns)],
            # The server may have IPv4 egress only.  Do not resolve proxied
            # destinations to AAAA and then fail the direct outbound; GitHub
            # (IPv4-only) worked while Google/Hugging Face timed out on hosts
            # without IPv6.  ipv4_only keeps the server usable on IPv4-only VPS.
            "strategy": "ipv4_only",
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
            # Resolve outbound domains through the internal ipv4_only DNS
            # instead of the OS resolver, which may prefer AAAA on an
            # IPv4-only VPS.
            "default_domain_resolver": {"server": "local"},
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
            "cache_file": {
                "enabled": True,
                "store_fakeip": True,
                **({"path": spec.cache_path} if spec.cache_path else {}),
            },
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
        # Only locally verified rule sets may reach sing-box.  A remote URL
        # here would make the privileged core fetch an operator-supplied URL
        # outside our SSRF/DNS policy, and would require network access on
        # every start.  ``POST /rule-sets/{id}/update`` downloads and
        # validates content into ``path`` first.
        if entry.get("path"):
            fmt = str(entry.get("format") or "binary").lower()
            if fmt == "srs":
                # 0.1.1 rows used the file extension as the format name; the
                # sing-box configuration expects "binary".
                fmt = "binary"
            defined[tag] = {
                "type": "local",
                "tag": tag,
                "format": fmt,
                "path": entry["path"],
            }
    return list(defined.values())


def _local_dns_server(value: str) -> dict[str, Any]:
    """Build the ``local`` entry without assuming a mainland resolver.

    ``local`` uses the operating system resolver and never hardcodes a
    third-party address.  Operators that need a specific UDP resolver can still
    set ``client_dns_local`` to an IP literal.
    """

    candidate = (value or "local").strip()
    if candidate.lower() in {"local", "system", "os"}:
        return {"type": "local", "tag": "local"}
    return {"type": "udp", "tag": "local", "server": candidate}


def _client_dns(spec: ClientConfigSpec, tun_enabled: bool) -> dict[str, Any]:
    if spec.routing_mode == "direct":
        # Direct mode must not send DNS queries through a proxy outbound that
        # is not used for traffic; use the local resolver only.
        return {
            "servers": [_local_dns_server(spec.dns_local)],
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
        _local_dns_server(spec.dns_local),
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
    groups: list[tuple[str, str, list[Endpoint]]],
) -> tuple[list[Endpoint], dict[tuple[str, str], str]]:
    """Make endpoint tags unique across profiles without renaming unique ones.

    ``groups`` carries ``(profile_id, display_name, endpoints)``.  The returned
    mapping is keyed by ``(profile_id, original_tag)`` so duplicate profile
    names cannot collide, while generated tags still use the readable name.
    """

    counts: dict[str, int] = {}
    for _group_key, _label, endpoints in groups:
        for endpoint in endpoints:
            counts[endpoint.tag] = counts.get(endpoint.tag, 0) + 1
    # Generated outbounds own these tags.  An endpoint called "proxy" or
    # "direct" would make the whole configuration fail validation.  Endpoint
    # tags that are already unique are reserved up front so a renamed
    # duplicate can never steal another profile's tag.
    reserved = {"auto", "proxy", "direct"}
    keep = {tag for tag, count in counts.items() if count == 1 and tag not in reserved}
    used = set(keep) | reserved
    flattened: list[Endpoint] = []
    mapping: dict[tuple[str, str], str] = {}
    for group_key, label, endpoints in groups:
        for endpoint in endpoints:
            effective = endpoint.tag
            if effective not in keep:
                prefix = _tag_slug(label)
                base = f"{prefix}-{endpoint.tag}"[:64]
                candidate = base
                suffix = 2
                while candidate in used:
                    candidate = f"{base[:58]}-{suffix}"
                    suffix += 1
                effective = candidate
                used.add(candidate)
            mapping[(group_key, endpoint.tag)] = effective
            flattened.append(
                endpoint
                if effective == endpoint.tag
                else endpoint.model_copy(update={"tag": effective})
            )
    return flattened, mapping


def _tag_slug(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")
    return (cleaned or "profile")[:24]
