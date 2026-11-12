from __future__ import annotations

import grpc
import pytest

from ostium.engine.singbox import v2ray_stats
from ostium.engine.singbox.v2ray_stats import StatsUnavailable, V2RayStatsClient


class FakeStat:
    def __init__(self, name: str, value: int) -> None:
        self.name = name
        self.value = value


class FakeResponse:
    def __init__(self, stats: list[FakeStat]) -> None:
        self.stat = stats


class FakeSysResponse:
    NumGoroutine = 1
    Alloc = 2
    Sys = 3
    LiveObjects = 4
    Uptime = 5


class FakeStub:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.queries = 0
        self.sys_calls = 0

    async def QueryStats(self, request, timeout):  # type: ignore[no-untyped-def]
        self.queries += 1
        if self.error:
            raise self.error
        return FakeResponse(
            [
                FakeStat("user>>>alice>>>traffic>>>uplink", 10),
                FakeStat("user>>>alice>>>traffic>>>downlink", 20),
                FakeStat("user>>>bob>>>traffic>>>uplink", 5),
                FakeStat("inbound>>>vless-in>>>traffic>>>uplink", 999),
                FakeStat("malformed", 1),
            ]
        )

    async def GetSysStats(self, request, timeout):  # type: ignore[no-untyped-def]
        self.sys_calls += 1
        if self.error:
            raise self.error
        return FakeSysResponse()


class FakeChannel:
    def __init__(self) -> None:
        self.closed = False

    def unary_unary(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return lambda *a, **k: None

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_query_users_parsing() -> None:
    client = V2RayStatsClient("127.0.0.1:1")
    stub = FakeStub()
    channel = FakeChannel()
    client._stub = stub  # type: ignore[assignment]
    client._channel = channel  # type: ignore[assignment]
    assert await client.query_users() == {"alice": (10, 20), "bob": (5, 0)}
    assert stub.queries == 1

    # The lazily-created stub is reused.
    assert await client._ensure() is stub


@pytest.mark.asyncio
async def test_query_users_timeout_closes_channel() -> None:
    client = V2RayStatsClient("127.0.0.1:1")
    client._stub = FakeStub(error=TimeoutError())  # type: ignore[assignment]
    channel = FakeChannel()
    client._channel = channel  # type: ignore[assignment]
    with pytest.raises(StatsUnavailable):
        await client.query_users()
    assert channel.closed is True
    assert client._stub is None
    assert client._channel is None

    client._stub = FakeStub(error=RuntimeError("rpc"))  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        await client.query_users()


@pytest.mark.asyncio
async def test_sys_stats_and_close() -> None:
    client = V2RayStatsClient()
    stub = FakeStub()
    channel = FakeChannel()
    client._stub = stub  # type: ignore[assignment]
    client._channel = channel  # type: ignore[assignment]
    assert await client.sys_stats() == {
        "goroutines": 1,
        "alloc": 2,
        "sys": 3,
        "live_objects": 4,
        "uptime": 5,
    }
    await client.close()
    assert channel.closed is True
    await client.close()  # idempotent

    client._stub = FakeStub(error=TimeoutError())  # type: ignore[assignment]
    client._channel = FakeChannel()  # type: ignore[assignment]
    with pytest.raises(StatsUnavailable):
        await client.sys_stats()
    assert client._channel is None


@pytest.mark.asyncio
async def test_query_users_rpc_error_and_channel_creation(monkeypatch) -> None:
    created: list[str] = []

    def fake_channel(address: str):  # type: ignore[no-untyped-def]
        created.append(address)
        return FakeChannel()

    monkeypatch.setattr(v2ray_stats.grpc.aio, "insecure_channel", fake_channel)
    client = V2RayStatsClient("127.0.0.1:19091")
    stub = await client._ensure()
    assert created == ["127.0.0.1:19091"]
    assert stub is client._stub

    error = grpc.aio.AioRpcError(
        grpc.StatusCode.UNAVAILABLE,
        grpc.aio.Metadata(),
        grpc.aio.Metadata(),
        details="down",
    )
    client._stub = FakeStub(error=error)  # type: ignore[assignment]
    with pytest.raises(StatsUnavailable):
        await client.query_users()
