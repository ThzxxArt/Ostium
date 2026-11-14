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
SCHEMA_HEAD = "d41f7a2c9b30"


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


ENCRYPTED_FIELD_PROBES = (
    ("admin_users", "totp_secret_enc"),
    ("proxy_users", "password_enc"),
    ("proxy_users", "ss_password_enc"),
    ("proxy_users", "subscription_token_enc"),
    ("profiles", "config_enc"),
    ("profiles", "subscription_url_enc"),
    ("inbounds", "params_enc"),
)


def database_requires_master_key(path: Path) -> bool:
    """Return True when an existing database contains fields encrypted at rest.

    ``master.key`` is written when the first encrypted field is created.  If the
    key disappears while ciphertext remains, generating a replacement key would
    make every password, TOTP secret, subscription token and inbound credential
    permanently unreadable.  Startup must fail closed instead.
    """

    if not path.is_file():
        return False
    try:
        with sqlite3.connect(path) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            for table, column in ENCRYPTED_FIELD_PROBES:
                if table not in tables:
                    continue
                row = connection.execute(
                    f"SELECT 1 FROM {table} WHERE {column} IS NOT NULL AND {column} != '' LIMIT 1"  # noqa: S608
                ).fetchone()
                if row is not None:
                    return True
            if "settings" in tables:
                row = connection.execute(
                    "SELECT 1 FROM settings WHERE value_json LIKE '%\"v1.%' LIMIT 1"
                ).fetchone()
                if row is not None:
                    return True
    except sqlite3.DatabaseError:
        # An unreadable database is not a reason to create a fresh key.
        return True
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
    """Run Alembic ``upgrade head`` synchronously with a snapshot and lock.

    Called before the app opens the database, so blocking briefly is preferable
    to serving requests against an unmigrated schema.  The Alembic environment
    is synchronous to avoid nested event loops.
    """

    from filelock import FileLock, Timeout

    db_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(db_path.with_suffix(".migrate.lock")), timeout=60)
    try:
        with lock:
            _check_version(db_path)
            snapshot = db_path.with_suffix(".pre-migrate.db")
            if db_path.is_file():
                _snapshot_database(db_path, snapshot)
            try:
                command.upgrade(_alembic_config(db_path), "head")
            except Exception:
                if snapshot.is_file():
                    # Restore the exact bytes SQLite produced, not a partial
                    # migration that would make the next start fail again.
                    for leftover in (
                        db_path.with_name(db_path.name + "-wal"),
                        db_path.with_name(db_path.name + "-shm"),
                    ):
                        leftover.unlink(missing_ok=True)
                    snapshot.replace(db_path)
                raise
            else:
                # The snapshot is a full copy of the encrypted database.  Keep
                # it only on failure; leaving it behind doubles disk usage and
                # retains an extra copy of every credential indefinitely.
                snapshot.unlink(missing_ok=True)
    except Timeout as exc:
        raise RuntimeError(f"another Ostium process is migrating {db_path}; try again") from exc


def _snapshot_database(source: Path, destination: Path) -> None:
    """Copy a consistent SQLite image, including committed WAL frames."""

    src = sqlite3.connect(source)
    dst = sqlite3.connect(destination)
    try:
        src.execute("PRAGMA wal_checkpoint(FULL)")
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    if os.name == "posix":
        try:
            destination.chmod(0o600)
        except OSError:
            pass


async def create_schema(engine: AsyncEngine) -> None:
    from ostium.db import models  # noqa: F401 - register mappers before create_all

    raw_path = engine.url.database
    if not raw_path:
        raise RuntimeError("the database URL does not contain a file path")
    db_path = Path(str(raw_path))
    fresh = not _has_tables(db_path)
    if not fresh and _read_version(db_path) is None:
        # A database with tables but no Alembic metadata cannot be upgraded
        # safely: running the initial revision would fail on existing tables
        # and leave the operator without a recovery path.
        raise DatabaseVersionError(
            f"database {db_path} has tables but no alembic_version; "
            "restore a backup or re-run the supported upgrade path"
        )
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
        _tighten_database_files(db_path)
        return
    _check_version(db_path)
    migrate_database(db_path)
    _tighten_database_files(db_path)


def _tighten_database_files(db_path: Path) -> None:
    if os.name != "posix":
        return
    for path in (
        db_path,
        db_path.with_name(db_path.name + "-wal"),
        db_path.with_name(db_path.name + "-shm"),
    ):
        tighten_permissions(path)


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
