"""Persistent key/value settings."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.db.models import Setting


async def get_setting(session: AsyncSession, key: str, default: Any = None) -> Any:
    row = await session.get(Setting, key)
    return row.value_json if row is not None else default


async def set_setting(session: AsyncSession, key: str, value: Any) -> None:
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value_json=value))
    else:
        row.value_json = value
    await session.flush()


async def all_settings(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.execute(select(Setting))).scalars().all()
    return {row.key: row.value_json for row in rows}


async def is_initialized(session: AsyncSession) -> bool:
    return bool(await get_setting(session, "initialized", False))
