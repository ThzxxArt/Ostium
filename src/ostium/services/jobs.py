"""Persistent long-running jobs with progress and cooperative cancellation."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ostium.db.models import Job
from ostium.services.events import EventBus
from ostium.util.time import iso, utcnow


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, manager: JobManager, job_id: str) -> None:
        self.manager = manager
        self.job_id = job_id
        self._cancel = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def request_cancel(self) -> None:
        self._cancel.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelled()

    async def progress(self, percent: int, message: str = "") -> None:
        self.raise_if_cancelled()
        await self.manager.update(self.job_id, progress=max(0, min(100, percent)), message=message)


JobFunction = Callable[[JobContext], Awaitable[dict[str, Any] | None]]


class JobManager:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], bus: EventBus) -> None:
        self.session_factory = session_factory
        self.bus = bus
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._contexts: dict[str, JobContext] = {}

    async def submit(self, job_type: str, function: JobFunction, *, message: str = "") -> Job:
        async with self.session_factory() as session:
            job = Job(type=job_type, message=message, status="queued")
            session.add(job)
            await session.commit()
            await session.refresh(job)
        context = JobContext(self, job.id)
        self._contexts[job.id] = context
        self._tasks[job.id] = asyncio.create_task(
            self._execute(job.id, function, context), name=f"job-{job.id}"
        )
        await self.bus.publish("job.created", {"id": job.id, "type": job_type})
        return job

    async def _execute(self, job_id: str, function: JobFunction, context: JobContext) -> None:
        await self.update(job_id, status="running", progress=1, message="starting", started=True)
        try:
            result = await function(context)
            await self.update(
                job_id,
                status="cancelled" if context.cancelled else "succeeded",
                progress=100,
                message="cancelled" if context.cancelled else "completed",
                result=result or {},
                finished=True,
            )
        except JobCancelled:
            await self.update(job_id, status="cancelled", message="cancelled", finished=True)
        except asyncio.CancelledError:
            await self.update(job_id, status="cancelled", message="cancelled", finished=True)
            raise
        except Exception as exc:
            await self.update(
                job_id, status="failed", message="failed", error=str(exc)[:2000], finished=True
            )
        finally:
            self._tasks.pop(job_id, None)
            self._contexts.pop(job_id, None)

    async def cancel(self, job_id: str) -> bool:
        context = self._contexts.get(job_id)
        if context is not None:
            context.request_cancel()
            task = self._tasks.get(job_id)
            if task is not None:
                task.cancel()
            return True
        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status not in {"queued", "running"}:
                return False
            job.status = "cancelled"
            job.cancel_requested = True
            job.finished_at = utcnow()
            await session.commit()
        return True

    async def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        started: bool = False,
        finished: bool = False,
    ) -> None:
        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            if status:
                job.status = status
            if progress is not None:
                job.progress = progress
            if message is not None:
                job.message = message[:500]
            if result is not None:
                job.result_json = result
            if error is not None:
                job.error = error
            if started and job.started_at is None:
                job.started_at = utcnow()
            if finished:
                job.finished_at = utcnow()
            await session.commit()
            payload = {
                "id": job.id,
                "type": job.type,
                "status": job.status,
                "progress": job.progress,
                "message": job.message,
                "error": job.error,
                "created_at": iso(job.created_at),
                "started_at": iso(job.started_at),
                "finished_at": iso(job.finished_at),
            }
        await self.bus.publish("job.updated", payload)

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        for task in list(self._tasks.values()):
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def recover_jobs(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        result = await session.execute(
            update(Job)
            .where(Job.status == "running")
            .values(status="interrupted", finished_at=utcnow())
        )
        await session.commit()
        return int(getattr(result, "rowcount", 0) or 0)


def serialize_job(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "type": job.type,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "result": job.result_json,
        "error": job.error,
        "cancel_requested": job.cancel_requested,
        "created_at": iso(job.created_at),
        "started_at": iso(job.started_at),
        "finished_at": iso(job.finished_at),
    }


async def list_jobs(session: AsyncSession, limit: int = 100) -> list[Job]:
    return list(
        (await session.execute(select(Job).order_by(Job.created_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
