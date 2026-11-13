from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError as SADatabaseError

from ostium.db import session as session_module
from ostium.db.session import (
    INITIAL_REVISION,
    SCHEMA_HEAD,
    DatabaseVersionError,
    check_database_integrity,
    create_engine,
    create_schema,
    create_session_factory,
    database_url,
    migrate_database,
    session_scope,
    tighten_permissions,
)


async def test_fresh_database_is_created_and_stamped(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    engine = create_engine(db)
    try:
        await create_schema(engine)
    finally:
        await engine.dispose()
    with sqlite3.connect(db) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "admin_users" in tables
        assert "alembic_version" in tables
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert version == SCHEMA_HEAD


async def test_existing_010_database_upgrades_in_place(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    engine = create_engine(db)
    try:
        await create_schema(engine)
    finally:
        await engine.dispose()
    # A 0.1.0 database is already stamped with the initial revision.
    migrate_database(db)
    with sqlite3.connect(db) as connection:
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == INITIAL_REVISION
        )


async def test_newer_schema_is_rejected(tmp_path: Path) -> None:
    db = tmp_path / "future.db"
    engine = create_engine(db)
    try:
        await create_schema(engine)
    finally:
        await engine.dispose()
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE alembic_version SET version_num='zzzzzzzzzzzz'")
        connection.commit()
    with pytest.raises(DatabaseVersionError, match="newer than this Ostium build"):
        migrate_database(db)


async def test_empty_existing_file_is_treated_as_fresh(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    db.touch()
    engine = create_engine(db)
    try:
        await create_schema(engine)
    finally:
        await engine.dispose()
    check_database_integrity(db)


def test_migrate_database_on_an_empty_file(tmp_path: Path) -> None:
    db = tmp_path / "alembic-empty.db"
    db.touch()
    migrate_database(db)
    with sqlite3.connect(db) as connection:
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == SCHEMA_HEAD
        )


def test_corrupt_database_version_read_is_tolerated(tmp_path: Path) -> None:
    db = tmp_path / "corrupt-version.db"
    db.write_bytes(b"not sqlite")
    with pytest.raises(SADatabaseError):
        migrate_database(db)


def test_missing_database_and_in_memory_engine(tmp_path: Path) -> None:
    assert session_module._read_version(tmp_path / "missing.db") is None

    from sqlalchemy.ext.asyncio import create_async_engine

    async def _run() -> None:
        engine = create_async_engine("sqlite+aiosqlite://")
        try:
            with pytest.raises(RuntimeError, match="file path"):
                await create_schema(engine)
        finally:
            await engine.dispose()

    import asyncio

    asyncio.run(_run())


def test_integrity_check_rejects_corruption(tmp_path: Path) -> None:
    good = tmp_path / "good.db"
    with sqlite3.connect(good) as connection:
        connection.execute("CREATE TABLE t (id INTEGER)")
    check_database_integrity(good)

    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a sqlite database at all")
    with pytest.raises(sqlite3.DatabaseError):
        check_database_integrity(bad)

    missing = tmp_path / "missing.db"
    with pytest.raises(RuntimeError, match="does not exist"):
        check_database_integrity(missing)


def test_database_url_and_permissions(tmp_path: Path) -> None:
    db = tmp_path / "x.db"
    assert database_url(db).startswith("sqlite+aiosqlite:///")
    target = tmp_path / "secret"
    target.write_text("x")
    tighten_permissions(target)
    if __import__("os").name == "posix":
        assert target.stat().st_mode & 0o777 == 0o600
    tighten_permissions(tmp_path / "missing")


async def test_session_scope_commits_and_rolls_back(tmp_path: Path) -> None:
    db = tmp_path / "scope.db"
    engine = create_engine(db)
    await create_schema(engine)
    factory = create_session_factory(engine)
    try:
        async with session_scope(factory) as session:
            await session.execute(text("CREATE TABLE IF NOT EXISTS demo (id INTEGER)"))
            await session.execute(text("INSERT INTO demo (id) VALUES (1)"))
        with pytest.raises(RuntimeError):
            async with session_scope(factory) as session:
                await session.execute(text("INSERT INTO demo (id) VALUES (2)"))
                raise RuntimeError("rollback")
        with sqlite3.connect(db) as connection:
            assert connection.execute("SELECT COUNT(*) FROM demo").fetchone()[0] == 1
    finally:
        await engine.dispose()
