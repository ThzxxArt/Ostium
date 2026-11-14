"""Async engine/session factory and schema migration bootstrap."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ostium.db.base import Base

INITIAL_REVISION = "8c9f85297917"
# Keep this in sync with the newest file under ``alembic/versions``.
SCHEMA_HEAD = INITIAL_REVISION


class DatabaseVersionError(RuntimeError):
    """The database was created by a newer Ostium release."""


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


def _migrations_dir() -> Path:
    """Locate the packaged Alembic environment (wheel) or the repo checkout."""

    candidates = [
        Path(__file__).resolve().parent / "alembic",
        Path(__file__).resolve().parents[3] / "alembic",
    ]
    for candidate in candidates:
        if (candidate / "env.py").is_file():
            return candidate
    raise RuntimeError("Ostium database migrations are not bundled with this installation")


def _alembic_config(db_path: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(_migrations_dir()))
    config.attributes["database_url"] = f"sqlite:///{db_path}"
    return config


def _read_version(db_path: Path) -> str | None:
    if not db_path.is_file():
        return None
    try:
        with sqlite3.connect(db_path) as connection:
            row = connection.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
            return str(row[0]) if row else None
    except sqlite3.DatabaseError:
        return None


def _has_tables(db_path: Path) -> bool:
    if not db_path.is_file():
        return False
    try:
        with sqlite3.connect(db_path) as connection:
            row = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='admin_users'"
            ).fetchone()
            return row is not None
    except sqlite3.DatabaseError:
        return False


def _check_version(db_path: Path) -> None:
    version = _read_version(db_path)
    if version is None:
        return
    # Revisions are opaque hashes, not sortable numbers.  Treat any revision
    # that is not part of this build's migration graph as incompatible instead
    # of guessing from a lexicographic comparison.
    try:
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(_alembic_config(db_path))
        known = {revision.revision for revision in script.walk_revisions()}
    except Exception as exc:  # pragma: no cover - bundling errors are fatal
        raise DatabaseVersionError(f"could not inspect bundled database migrations: {exc}") from exc
    if version not in known:
        raise DatabaseVersionError(
            f"database schema revision {version} is newer than this Ostium build "
            f"({SCHEMA_HEAD}); upgrade Ostium or restore a compatible backup"
        )


def migrate_database(db_path: Path) -> None:
    """Run Alembic ``upgrade head`` synchronously.

    Called before the app opens the database, so blocking briefly is preferable
    to serving requests against an unmigrated schema.  The Alembic environment
    is synchronous to avoid nested event loops.
    """

    db_path.parent.mkdir(parents=True, exist_ok=True)
    _check_version(db_path)
    command.upgrade(_alembic_config(db_path), "head")


async def create_schema(engine: AsyncEngine) -> None:
    from ostium.db import models  # noqa: F401 - register mappers before create_all

    raw_path = engine.url.database
    if not raw_path:
        raise RuntimeError("the database URL does not contain a file path")
    db_path = Path(str(raw_path))
    fresh = not _has_tables(db_path)
    if fresh:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
            if "alembic_version" not in names:
                await connection.exec_driver_sql(
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
            await connection.exec_driver_sql(
                "INSERT OR IGNORE INTO alembic_version(version_num) VALUES (?)",
                (SCHEMA_HEAD,),
            )
        return
    _check_version(db_path)
    migrate_database(db_path)


def check_database_integrity(path: Path) -> None:
    """Raise when SQLite reports corruption; used before backup/restore swaps."""

    if not path.is_file():
        raise RuntimeError(f"database does not exist: {path}")
    with sqlite3.connect(path) as connection:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        if row is None or str(row[0]).lower() != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {row[0] if row else 'no result'}")


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
