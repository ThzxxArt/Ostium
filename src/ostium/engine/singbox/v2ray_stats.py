"""V2Ray gRPC statistics client for the Ostium sing-box build."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import grpc

from ostium.engine.singbox import v2ray_stats_pb2 as pb
from ostium.engine.singbox.v2ray_stats_pb2_grpc import StatsServiceStub

_USER_PATTERN = re.compile(r"^user>>>(?P<name>[^>]+)>>>traffic>>>(?P<direction>uplink|downlink)$")


class StatsUnavailable(Exception):
    pass


class V2RayStatsClient:
    def __init__(self, address: str = "127.0.0.1:19091") -> None:
        self.address = address
        self._channel: grpc.aio.Channel | None = None
        self._stub: StatsServiceStub | None = None
        self._lock = asyncio.Lock()

    async def _ensure(self) -> StatsServiceStub:
        async with self._lock:
            if self._stub is None:
                self._channel = grpc.aio.insecure_channel(self.address)
                self._stub = StatsServiceStub(self._channel)
            return self._stub

    async def query_users(self, timeout: float = 5.0) -> dict[str, tuple[int, int]]:
        stub = await self._ensure()
        request = pb.QueryStatsRequest(
            patterns=[r"^user>>>[^>]+>>>traffic>>>(uplink|downlink)$"], regexp=True
        )
        try:
            response = await stub.QueryStats(request, timeout=timeout)
        except (TimeoutError, grpc.aio.AioRpcError) as exc:
            await self.close()
            raise StatsUnavailable(str(exc)) from exc
        result: dict[str, tuple[int, int]] = {}
        for stat in response.stat:
            match = _USER_PATTERN.match(stat.name)
            if not match:
                continue
            name = match.group("name")
            up, down = result.get(name, (0, 0))
            if match.group("direction") == "uplink":
                up = int(stat.value)
            else:
                down = int(stat.value)
            result[name] = (up, down)
        return result

    async def sys_stats(self, timeout: float = 5.0) -> dict[str, Any]:
        stub = await self._ensure()
        try:
            response = await stub.GetSysStats(pb.SysStatsRequest(), timeout=timeout)
        except (TimeoutError, grpc.aio.AioRpcError) as exc:
            await self.close()
            raise StatsUnavailable(str(exc)) from exc
        return {
            "goroutines": response.NumGoroutine,
            "alloc": response.Alloc,
            "sys": response.Sys,
            "live_objects": response.LiveObjects,
            "uptime": response.Uptime,
        }

    async def close(self) -> None:
        async with self._lock:
            if self._channel is not None:
                await self._channel.close()
            self._channel = None
            self._stub = None
