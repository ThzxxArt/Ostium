"""Structural and real-binary checks for generated subscription profiles."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from django.conf import settings

from ostium.proxy.models import ProxyUser

from .endpoints import Endpoint, build_endpoints
from .renderers import render_base64, render_clash, render_singbox, render_uri_list
from .services import public_host

PASS = "pass"  # noqa: S105 - status label, not a credential
FAIL = "fail"
SKIP = "skip"


@dataclass(frozen=True, slots=True)
class CheckResult:
    key: str
    label: str
    status: str
    detail: str

    @property
    def ok(self) -> bool:
        return self.status != FAIL


def _binary(name: str, *, setting: str | None = None) -> str | None:
    if setting:
        configured = Path(setting)
        if configured.is_file():
            return str(configured.resolve())
    found = shutil.which(name)
    if found:
        return str(Path(found).resolve())
    for candidate in (Path(".cache/bin") / name, Path("tests/bin") / name):
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def _run(command: list[str], *, timeout: int = 30) -> tuple[bool, str]:
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if proc.returncode == 0:
        return True, "通过"
    output = (proc.stderr or proc.stdout or "").strip().splitlines()
    return False, (output[-1] if output else f"退出码 {proc.returncode}")[:240]


def _check_clash(endpoints: list[Endpoint]) -> CheckResult:
    body = render_clash(endpoints)
    try:
        payload = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        return CheckResult("clash", "Clash / Mihomo YAML", FAIL, f"YAML 解析失败：{exc}")
    if not isinstance(payload, dict):
        return CheckResult("clash", "Clash / Mihomo YAML", FAIL, "顶层不是对象")
    forbidden = [
        key for key in ("dns", "mixed-port", "mode", "log-level", "ipv6", "allow-lan", "bind-address") if key in payload
    ]
    if forbidden:
        return CheckResult("clash", "Clash / Mihomo YAML", FAIL, f"不应包含客户端设置：{', '.join(forbidden)}")
    if "1.1.1.1" in body:
        return CheckResult("clash", "Clash / Mihomo YAML", FAIL, "不应硬编码 1.1.1.1")
    rules = payload.get("rules") or []
    if any(str(rule).startswith(("GEOIP,", "GEOSITE,")) for rule in rules):
        return CheckResult("clash", "Clash / Mihomo YAML", FAIL, "不应依赖外部 GeoIP/Geosite 数据库")
    if not rules or rules[-1] != "MATCH,Ostium":
        return CheckResult("clash", "Clash / Mihomo YAML", FAIL, "缺少 MATCH,Ostium 兜底规则")
    proxies = payload.get("proxies") or []
    if len(proxies) != len(endpoints):
        return CheckResult("clash", "Clash / Mihomo YAML", FAIL, f"节点数量不一致：{len(proxies)} != {len(endpoints)}")
    return CheckResult("clash", "Clash / Mihomo YAML", PASS, f"{len(proxies)} 个节点，{len(rules)} 条规则")


def _check_singbox(endpoints: list[Endpoint]) -> CheckResult:
    body = render_singbox(endpoints)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return CheckResult("singbox", "sing-box JSON", FAIL, f"JSON 解析失败：{exc}")
    if "dns" in payload:
        return CheckResult("singbox", "sing-box JSON", FAIL, "不应覆盖客户端 DNS")
    route = payload.get("route") or {}
    if "default_domain_resolver" in route:
        return CheckResult("singbox", "sing-box JSON", FAIL, "不应强制 default_domain_resolver")
    if route.get("final") != "Ostium":
        return CheckResult("singbox", "sing-box JSON", FAIL, "route.final 不是 Ostium")
    outbounds = payload.get("outbounds") or []
    if len(outbounds) < len(endpoints) + 3:
        return CheckResult("singbox", "sing-box JSON", FAIL, "出站数量不足")
    return CheckResult("singbox", "sing-box JSON", PASS, f"{len(outbounds)} 个出站")


def _check_uris(endpoints: list[Endpoint]) -> CheckResult:
    text = render_uri_list(endpoints)
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) != len(endpoints):
        return CheckResult("uri", "URI / Base64", FAIL, f"URI 数量不一致：{len(lines)} != {len(endpoints)}")
    schemes = [urlsplit(line).scheme for line in lines]
    expected = {"vless", "hysteria2", "trojan", "ss"}
    if not set(schemes).issubset(expected):
        return CheckResult("uri", "URI / Base64", FAIL, f"未知 URI 协议：{', '.join(schemes)}")
    encoded = render_base64(endpoints)
    if base64.b64decode(encoded).decode("utf-8") != text:
        return CheckResult("uri", "URI / Base64", FAIL, "Base64 往返不一致")
    return CheckResult("uri", "URI / Base64", PASS, f"{len(lines)} 条：{' / '.join(schemes)}")


def _xray_config(endpoints: list[Endpoint]) -> dict | None:
    outbounds = []
    for endpoint in endpoints:
        if endpoint.protocol == "vless":
            outbounds.append(
                {
                    "tag": endpoint.name,
                    "protocol": "vless",
                    "settings": {
                        "vnext": [
                            {
                                "address": endpoint.server,
                                "port": endpoint.port,
                                "users": [
                                    {
                                        "id": endpoint.uuid,
                                        "encryption": "none",
                                        "flow": endpoint.flow or "xtls-rprx-vision",
                                    }
                                ],
                            }
                        ]
                    },
                    "streamSettings": {
                        "network": "tcp",
                        "security": "reality",
                        "realitySettings": {
                            "serverName": endpoint.sni or endpoint.server,
                            "fingerprint": "chrome",
                            "publicKey": endpoint.reality_public_key,
                            "shortId": endpoint.reality_short_id or "",
                        },
                    },
                }
            )
        elif endpoint.protocol == "trojan":
            outbounds.append(
                {
                    "tag": endpoint.name,
                    "protocol": "trojan",
                    "settings": {
                        "servers": [
                            {
                                "address": endpoint.server,
                                "port": endpoint.port,
                                "password": endpoint.password,
                            }
                        ]
                    },
                    "streamSettings": {
                        "network": "tcp",
                        "security": "tls",
                        "tlsSettings": {"serverName": endpoint.sni or endpoint.server},
                    },
                }
            )
        elif endpoint.protocol == "shadowsocks":
            outbounds.append(
                {
                    "tag": endpoint.name,
                    "protocol": "shadowsocks",
                    "settings": {
                        "servers": [
                            {
                                "address": endpoint.server,
                                "port": endpoint.port,
                                "method": endpoint.method,
                                "password": endpoint.ss_password,
                            }
                        ]
                    },
                }
            )
    if not outbounds:
        return None
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "check-in",
                "listen": "127.0.0.1",
                "port": 17896,
                "protocol": "socks",
                "settings": {"udp": False},
            }
        ],
        "outbounds": outbounds,
    }


def _binary_checks(endpoints: list[Endpoint], *, enabled: bool) -> list[CheckResult]:
    if not enabled:
        return [
            CheckResult("mihomo", "Mihomo 配置校验", SKIP, "已禁用二进制检查"),
            CheckResult("singbox-bin", "sing-box 配置校验", SKIP, "已禁用二进制检查"),
            CheckResult("xray", "Xray 配置校验", SKIP, "已禁用二进制检查"),
        ]

    results: list[CheckResult] = []
    with tempfile.TemporaryDirectory(prefix="ostium-check-") as directory:
        root = Path(directory)

        mihomo = _binary("mihomo")
        if mihomo:
            path = root / "clash.yaml"
            path.write_text(render_clash(endpoints), encoding="utf-8")
            ok, detail = _run([mihomo, "-t", "-f", str(path)])
            results.append(CheckResult("mihomo", "Mihomo 配置校验", PASS if ok else FAIL, detail))
        else:
            results.append(CheckResult("mihomo", "Mihomo 配置校验", SKIP, "未安装 mihomo"))

        singbox = _binary("sing-box", setting=settings.OSTIUM_SINGBOX_PATH)
        if singbox:
            path = root / "singbox.json"
            path.write_text(render_singbox(endpoints), encoding="utf-8")
            ok, detail = _run([singbox, "check", "-c", str(path)])
            results.append(CheckResult("singbox-bin", "sing-box 配置校验", PASS if ok else FAIL, detail))
        else:
            results.append(CheckResult("singbox-bin", "sing-box 配置校验", SKIP, "未安装 sing-box"))

        xray = _binary("xray")
        xray_config = _xray_config(endpoints)
        if xray and xray_config:
            path = root / "xray.json"
            path.write_text(json.dumps(xray_config, indent=2), encoding="utf-8")
            ok, detail = _run([xray, "run", "-test", "-c", str(path)])
            results.append(CheckResult("xray", "Xray 配置校验", PASS if ok else FAIL, detail))
        elif xray:
            results.append(CheckResult("xray", "Xray 配置校验", SKIP, "当前线路没有 Xray 支持的协议"))
        else:
            results.append(CheckResult("xray", "Xray 配置校验", SKIP, "未安装 xray"))
    return results


def check_subscription(
    user: ProxyUser,
    *,
    host: str | None = None,
    run_binaries: bool = True,
) -> list[CheckResult]:
    """Validate one user's generated profiles without sending network traffic."""

    endpoints = build_endpoints(user, host or public_host(None))
    if not endpoints:
        return [CheckResult("endpoints", "可用线路", FAIL, "没有启用的线路或证书未就绪")]
    results = [
        CheckResult(
            "endpoints",
            "可用线路",
            PASS,
            f"{len(endpoints)} 条：{' / '.join(item.protocol for item in endpoints)}",
        ),
        _check_clash(endpoints),
        _check_singbox(endpoints),
        _check_uris(endpoints),
    ]
    results.extend(_binary_checks(endpoints, enabled=run_binaries))
    return results


__all__ = ["FAIL", "PASS", "SKIP", "CheckResult", "check_subscription"]
