"""Async engine/session factory and schema bootstrap."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ostium.db.base import Base

INITIAL_REVISION = "8c9f85297917"


def database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path}"


def create_engine(path: Path, *, echo: bool = False) -> AsyncEngine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(
        database_url(path),
        echo=echo,
        future=True,
        pool_pre_ping=True,
        connect_args={"timeout": 30},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection: object, _record: object) -> None:  # pragma: no cover
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def create_schema(engine: AsyncEngine) -> None:
    from ostium.db import models  # noqa: F401 - register mappers before create_all

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        await connection.exec_driver_sql(
            "INSERT OR IGNORE INTO alembic_version(version_num) VALUES (?)",
            (INITIAL_REVISION,),
        )


@asynccontextmanager
async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    session = factory()
    try:
        yield session
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    finally:
        await session.close()


def tighten_permissions(path: Path) -> None:
    if os.name == "posix" and path.exists():
        try:
            path.chmod(0o600)
        except OSError:
            pass
