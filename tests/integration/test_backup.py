from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select

from ostium.config import Role, Settings
from ostium.db.models import AdminUser, ProxyUser
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.auth import create_admin
from ostium.services.backup import create_backup, restore_backup
from ostium.services.crypto import SecretStore
from ostium.services.users import create_user


def _settings(tmp_path: Path, name: str) -> Settings:
    data = tmp_path / name
    value = Settings(
        role=Role.SERVER,
        data_dir=data,
        config_dir=tmp_path / f"{name}-config",
        state_dir=tmp_path / f"{name}-state",
        core_token_file=data / "runtime" / "core.token",
        engine_path=str(data / "core" / "sing-box"),
        dev=True,
        log_level="warning",
    )
    value.paths.ensure()
    value.save()
    return value


async def _seed(settings: Settings) -> None:
    engine = create_engine(settings.paths.db_path)
    await create_schema(engine)
    factory = create_session_factory(engine)
    store = SecretStore.from_data_dir(settings.data_dir)
    async with factory() as session:
        await create_admin(session, username="admin", password="verysecret123")
        await create_user(session, store, name="alice", quota_bytes=100)
        await session.commit()
    await engine.dispose()


def test_backup_and_restore_roundtrip(tmp_path: Path) -> None:
    source = _settings(tmp_path, "source")
    asyncio.run(_seed(source))
    result = create_backup(source, password="backup-password")
    backup_path = Path(result["path"])
    assert backup_path.is_file()
    assert result["encrypted"] is True

    target = _settings(tmp_path, "target")
    restored = restore_backup(target, backup_path, password="backup-password")
    assert restored["restored"] is True
    assert target.paths.master_key_path.is_file()

    async def _verify() -> tuple[int, int]:
        engine = create_engine(target.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            admins = (await session.execute(select(AdminUser))).scalars().all()
            users = (await session.execute(select(ProxyUser))).scalars().all()
        await engine.dispose()
        return len(admins), len(users)

    assert asyncio.run(_verify()) == (1, 1)


def test_encrypted_backup_requires_password(tmp_path: Path) -> None:
    source = _settings(tmp_path, "source2")
    asyncio.run(_seed(source))
    result = create_backup(source, password="backup-password")
    target = _settings(tmp_path, "target2")
    try:
        restore_backup(target, Path(result["path"]))
    except Exception as exc:
        assert "password" in str(exc).lower()
    else:
        raise AssertionError("restore without password should fail")
