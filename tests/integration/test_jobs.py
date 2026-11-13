from __future__ import annotations

import asyncio
from pathlib import Path

from ostium.config import Settings
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.events import EventBus
from ostium.services.jobs import JobManager, recover_jobs, serialize_job


def test_job_success_and_failure(tmp_path: Path, settings: Settings) -> None:
    async def _run() -> None:
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        bus = EventBus()
        manager = JobManager(factory, bus)

        async def success(context):  # type: ignore[no-untyped-def]
            await context.progress(50, "half")
            return {"ok": True}

        async def failure(context):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        job = await manager.submit("test.success", success)
        await asyncio.sleep(0.1)
        async with factory() as session:
            from ostium.db.models import Job

            row = await session.get(Job, job.id)
            assert row is not None
            assert row.status == "succeeded"
            assert row.result_json == {"ok": True}
            assert serialize_job(row)["progress"] == 100

        job = await manager.submit("test.failure", failure)
        await asyncio.sleep(0.1)
        async with factory() as session:
            from ostium.db.models import Job

            row = await session.get(Job, job.id)
            assert row is not None
            assert row.status == "failed"
            assert "boom" in (row.error or "")

        interrupted = await recover_jobs(factory)
        assert interrupted >= 0
        await manager.shutdown()
        await engine.dispose()

    asyncio.run(_run())


def test_job_cancel(tmp_path: Path, settings: Settings) -> None:
    async def _run() -> None:
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        manager = JobManager(factory, EventBus())

        async def slow(context):  # type: ignore[no-untyped-def]
            for _ in range(50):
                context.raise_if_cancelled()
                await asyncio.sleep(0.05)

        job = await manager.submit("test.slow", slow)
        await asyncio.sleep(0.05)
        assert await manager.cancel(job.id)
        await asyncio.sleep(0.15)
        async with factory() as session:
            from ostium.db.models import Job

            row = await session.get(Job, job.id)
            assert row is not None
            assert row.status == "cancelled"
        await manager.shutdown()
        await engine.dispose()

    asyncio.run(_run())
