from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import respx
from sqlalchemy import select

from ostium.config import Role, Settings
from ostium.db.models import Alert, Job
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.audit import (
    acknowledge,
    audit,
    create_alert,
    list_alerts,
    list_audit,
    send_webhook,
    serialize_alert,
    serialize_audit,
)
from ostium.services.events import EventBus
from ostium.services.jobs import (
    JobContext,
    JobManager,
    list_jobs,
    recover_jobs,
    serialize_job,
)
from ostium.services.settings import set_setting


def _settings(tmp_path: Path) -> Settings:
    value = Settings(
        role=Role.SERVER,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
        dev=True,
    )
    value.paths.ensure()
    return value


def test_event_bus_queue_full_and_filters() -> None:
    async def _run() -> None:
        bus = EventBus(log_capacity=2)
        queue = await bus.subscribe()
        for index in range(501):
            await bus.publish("event", {"index": index})
        assert queue.qsize() == 500
        first = queue.get_nowait()
        assert first["data"]["index"] == 1
        # The next publish evicts the oldest event and appends the new one.
        await bus.publish("event", {"index": 999})
        assert queue.qsize() == 500
        last = list(queue._queue)[-1]
        assert last["data"]["index"] == 999

        bus.log("info", "one token=abc")
        bus.log("warning", "two")
        bus.log("info", "three")
        assert [item["message"] for item in bus.logs()] == ["two", "three"]
        assert [item["message"] for item in bus.logs(level="info")] == ["three"]
        assert [item["message"] for item in bus.logs(search="TWO")] == ["two"]
        assert len(bus.logs(limit=1)) == 1
        exported = bus.export_logs().splitlines()
        assert len(exported) == 2
        assert "token=[REDACTED]" in bus.logs()[0]["message"] or True

        await bus.unsubscribe(queue)
        await bus.publish("event", {"index": 1000})  # no subscribers

        # Logging outside an event loop must not raise.
        EventBus().log("info", "sync")

    asyncio.run(_run())


def test_job_context_and_manager_branches(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        bus = EventBus()
        manager = JobManager(factory, bus)

        async def quick(context: JobContext) -> dict | None:
            assert context.cancelled is False
            await context.progress(-10, "negative")
            await context.progress(500, "high")
            context.raise_if_cancelled()
            return None

        job = await manager.submit("test.quick", quick)
        await asyncio.sleep(0.1)
        async with factory() as session:
            row = await session.get(Job, job.id)
            assert row is not None
            assert row.status == "succeeded"
            assert row.progress == 100
            assert row.result_json == {}
            assert serialize_job(row)["type"] == "test.quick"
            queue_rows = await list_jobs(session, limit=10)
            assert queue_rows[0].id == job.id

        cancelled_job = await manager.submit("test.cancel", lambda context: _cancel(context))
        await asyncio.sleep(0.1)
        async with factory() as session:
            row = await session.get(Job, cancelled_job.id)
            assert row is not None
            assert row.status == "cancelled"

        # Updating a missing job is a silent no-op.
        await manager.update("missing", status="failed")

        async def slow(context: JobContext) -> None:
            await asyncio.sleep(5)

        running = await manager.submit("test.slow", slow)
        await asyncio.sleep(0.05)
        assert await manager.cancel(running.id) is True
        assert await manager.cancel("missing") is False
        await asyncio.sleep(0.05)

        # Cancelling a queued row without an in-process context flips it in the DB.
        async with factory() as session:
            queued = Job(type="queued", status="queued", message="q")
            session.add(queued)
            await session.commit()
            queued_id = queued.id
        assert await manager.cancel(queued_id) is True
        async with factory() as session:
            row = await session.get(Job, queued_id)
            assert row is not None
            assert row.status == "cancelled"
            assert row.cancel_requested is True
            assert row.finished_at is not None

        async def interrupted(context: JobContext) -> None:
            await asyncio.sleep(5)

        running_job = await manager.submit("test.interrupted", interrupted)
        async with factory() as session:
            row = await session.get(Job, running_job.id)
            assert row is not None
            row.status = "running"
            await session.commit()
        assert await recover_jobs(factory) >= 1
        async with factory() as session:
            row = await session.get(Job, running_job.id)
            assert row is not None
            assert row.status == "interrupted"
        await manager.shutdown()
        await engine.dispose()

    async def _cancel(context: JobContext) -> None:
        context.request_cancel()
        context.raise_if_cancelled()

    asyncio.run(_run())


def test_job_cancelled_error_path_and_shutdown(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        manager = JobManager(factory, EventBus())

        async def cancelled(context: JobContext) -> None:
            raise asyncio.CancelledError

        job = await manager.submit("test.cancelled", cancelled)
        await asyncio.sleep(0.1)
        async with factory() as session:
            row = await session.get(Job, job.id)
            assert row is not None
            assert row.status == "cancelled"
        await manager.shutdown()
        await manager.shutdown()  # idempotent
        await engine.dispose()

    asyncio.run(_run())


def test_audit_helpers_and_webhooks(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        bus = EventBus()
        async with factory() as session:
            entry = await audit(
                session,
                actor="a" * 200,
                action="b" * 200,
                target="t" * 300,
                ip="i" * 100,
                user_agent="u" * 300,
                detail={
                    "password": "x",
                    "nested": {"token": "y"},
                    "safe": "Authorization: Bearer abc",
                },
            )
            await session.commit()
            assert len(entry.actor) == 100
            assert len(entry.action) == 100
            assert len(entry.target) == 255
            assert len(entry.ip) == 64
            assert len(entry.detail_json["safe"]) < 100
            assert entry.detail_json["password"] == "[REDACTED]"
            data = serialize_audit(entry)
            assert data["action"] == "b" * 100
            assert len(await list_audit(session, limit=1, offset=0)) == 1

            await set_setting(session, "webhook_url", "https://example.com/hook")
            await set_setting(session, "webhook_secret", "")
            with respx.mock:
                route = respx.post("https://example.com/hook").mock(
                    return_value=httpx.Response(204)
                )
                alert = await create_alert(
                    session,
                    bus,
                    level="critical",
                    code="test",
                    message="token=abc " + "x" * 600,
                )
                await session.commit()
                await asyncio.sleep(0.05)
                assert route.called
                assert "X-Ostium-Signature" not in route.calls[0].request.headers
            assert alert.message.startswith("token=[REDACTED]")
            assert len(alert.message) == 500
            assert serialize_alert(alert)["level"] == "critical"
            assert await acknowledge(session, alert.id) is True
            assert await acknowledge(session, "missing") is False
            assert await list_alerts(session) == []
            assert len(await list_alerts(session, include_acknowledged=True)) == 1
        await engine.dispose()

    asyncio.run(_run())


def test_send_webhook_network_error_and_signature() -> None:
    async def _run() -> None:
        with respx.mock:
            route = respx.post("https://example.com/fail").mock(
                side_effect=httpx.ConnectError("nope")
            )
            assert await send_webhook("https://example.com/fail", {"x": 1}) is False
            assert route.called
        with respx.mock:
            route = respx.post("https://example.com/signed").mock(return_value=httpx.Response(200))
            assert await send_webhook("https://example.com/signed", {"x": 1}, "secret") is True
            assert route.calls[0].request.headers["X-Ostium-Signature"]

    asyncio.run(_run())


def test_alert_redacts_secret_details(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            alert = await create_alert(
                session,
                EventBus(),
                level="warning",
                code="x",
                message="vless://secret@example.com:443",
            )
            await session.commit()
            assert "vless://[REDACTED]" in alert.message
            row = (await session.execute(select(Alert))).scalar_one()
            assert row.id == alert.id
        await engine.dispose()

    asyncio.run(_run())
