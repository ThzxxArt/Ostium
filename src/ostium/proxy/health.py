"""Inbound health checks and anti-blocking rotation helpers."""

from __future__ import annotations

import secrets
import socket
from dataclasses import dataclass

import psutil

from ostium.operations.models import RuntimeState
from ostium.proxy.models import Inbound

REALITY_TARGETS = (
    "www.microsoft.com",
    "www.apple.com",
    "www.cloudflare.com",
    "www.amazon.com",
    "www.bing.com",
    "www.samsung.com",
    "www.icloud.com",
    "www.tesla.com",
    "www.nvidia.com",
    "www.adobe.com",
)


@dataclass(slots=True)
class InboundHealth:
    kind: str
    label: str
    status: str  # ok | warn | fail | disabled
    detail: str
    fix: str = ""


def _connections() -> list:
    try:
        return list(psutil.net_connections(kind="inet"))
    except psutil.Error, OSError:
        return []


def _listening(record: Inbound, connections: list) -> bool:
    socket_type = socket.SOCK_DGRAM if record.kind == Inbound.Kind.HYSTERIA2 else socket.SOCK_STREAM
    for connection in connections:
        address = connection.laddr
        if not address or address.port != record.port:
            continue
        if int(connection.type) != int(socket_type):
            continue
        if socket_type == socket.SOCK_STREAM and connection.status != psutil.CONN_LISTEN:
            continue
        return True
    return False


def _occupied_ports(connections: list) -> set[tuple[int, int]]:
    occupied = set()
    for connection in connections:
        address = connection.laddr
        if address:
            occupied.add((int(address.port), int(connection.type)))
    return occupied


def check_inbounds(
    *,
    connections: list | None = None,
    singbox_running: bool | None = None,
) -> list[InboundHealth]:
    """Return health for every configured inbound without changing state."""

    records = list(Inbound.objects.order_by("kind"))
    if connections is None:
        connections = _connections()
    if singbox_running is None:
        singbox_running = RuntimeState.load().singbox_running

    results: list[InboundHealth] = []
    for record in records:
        label = record.short_label
        if not record.enabled:
            results.append(InboundHealth(record.kind, label, "disabled", "未启用", "在控制台启用此线路。"))
            continue

        errors = record.validation_errors()
        if errors:
            results.append(
                InboundHealth(
                    record.kind,
                    label,
                    "fail",
                    "；".join(errors),
                    "修复证书、密钥或端口配置后重新应用。",
                )
            )
            continue

        if not singbox_running:
            results.append(
                InboundHealth(
                    record.kind,
                    label,
                    "fail",
                    "sing-box 未运行",
                    "检查 ostium-worker 与 sing-box 日志。",
                )
            )
            continue

        if not _listening(record, connections):
            transport = "UDP" if record.kind == Inbound.Kind.HYSTERIA2 else "TCP"
            results.append(
                InboundHealth(
                    record.kind,
                    label,
                    "fail",
                    f"端口 {record.port}/{transport} 未监听",
                    "检查端口冲突、防火墙和 sing-box 日志。变更端口后需在云防火墙放行。",
                )
            )
            continue

        params = record.params
        if record.kind == Inbound.Kind.HYSTERIA2 and not params.get("obfs_password"):
            results.append(
                InboundHealth(
                    record.kind,
                    label,
                    "warn",
                    "端口正常，但未启用 salamander 混淆",
                    "建议启用混淆；轮换混淆后需要重新分发订阅。",
                )
            )
            continue

        results.append(
            InboundHealth(
                record.kind,
                label,
                "ok",
                "端口正常，配置就绪",
                "",
            )
        )
    return results


def pick_random_port(record: Inbound, *, connections: list | None = None) -> int:
    """Pick a high port that is free for this inbound's transport."""

    if connections is None:
        connections = _connections()
    socket_type = socket.SOCK_DGRAM if record.kind == Inbound.Kind.HYSTERIA2 else socket.SOCK_STREAM
    occupied = _occupied_ports(connections)
    used_by_ostium = {
        (item.port, socket_type)
        for item in Inbound.objects.exclude(pk=record.pk)
        if (item.kind == Inbound.Kind.HYSTERIA2) == (record.kind == Inbound.Kind.HYSTERIA2)
    }
    for _ in range(200):
        port = 20000 + secrets.randbelow(40000)
        if port == record.port:
            continue
        if (port, socket_type) in occupied or (port, socket_type) in used_by_ostium:
            continue
        return port
    raise RuntimeError("Could not find a free high port.")


def _target_reachable(host: str) -> bool:
    try:
        with socket.create_connection((host, 443), timeout=2):
            return True
    except OSError:
        return False


def pick_reality_target(current: str | None = None, *, checker=None) -> str:
    """Pick a reachable TLS camouflage target different from the current one."""

    checker = checker or _target_reachable
    candidates = [item for item in REALITY_TARGETS if item != current]
    randomness = secrets.SystemRandom()
    randomness.shuffle(candidates)
    for host in candidates[:6]:
        if checker(host):
            return host
    raise RuntimeError("No reachable Reality camouflage target is available.")


__all__ = [
    "REALITY_TARGETS",
    "InboundHealth",
    "check_inbounds",
    "pick_random_port",
    "pick_reality_target",
]
