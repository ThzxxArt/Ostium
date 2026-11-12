from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import respx

from ostium.config import Role, Settings
from ostium.db.models import RuleSet
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.rules import update_rule_set


def test_update_rule_set_atomic(tmp_path: Path) -> None:
    settings = Settings(
        role=Role.CLIENT,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
        dev=True,
    )
    settings.paths.ensure()

    async def _run() -> None:
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        async with factory() as session:
            rule_set = RuleSet(name="test", url="https://example.com/test.srs", format="binary")
            session.add(rule_set)
            await session.commit()
            with respx.mock:
                respx.get("https://example.com/test.srs").mock(
                    return_value=httpx.Response(
                        200, content=b"binary-rules", headers={"etag": '"abc"'}
                    )
                )
                result = await update_rule_set(session, settings, rule_set)
                await session.commit()
            assert result["updated"] is True
            assert rule_set.path is not None
            assert Path(rule_set.path).read_bytes() == b"binary-rules"
            assert rule_set.etag == '"abc"'
        await engine.dispose()

    asyncio.run(_run())
