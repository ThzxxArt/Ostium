from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import respx

from ostium.config import Role, Settings
from ostium.db.models import RuleSet
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.rules import (
    evaluate,
    matches,
    path_for,
    serialize_rule_set,
    update_rule_set,
)


def test_all_match_types_and_failures() -> None:
    target = {
        "domain": "www.example.com",
        "ip": "10.1.2.3",
        "port": 443,
        "source_port": 443,
        "network": "tcp",
        "protocol": "tls",
        "process_name": "curl",
    }
    assert matches({"domain": ["www.example.com"]}, target) is True
    assert matches({"domain": ["other.example.com"]}, target) is False
    assert matches({"domain_suffix": ["example.com"]}, target) is True
    assert matches({"domain_suffix": [".net"]}, target) is False
    assert matches({"domain_keyword": ["example"]}, target) is True
    assert matches({"domain_keyword": ["missing"]}, target) is False
    assert matches({"domain_regex": [r"^www\."]}, target) is True
    assert matches({"domain_regex": [r"^mail\."]}, target) is False
    assert matches({"domain_regex": ["["]}, target) is False
    assert matches({"ip_cidr": ["10.0.0.0/8"]}, target) is True
    assert matches({"ip_cidr": ["192.168.0.0/16"]}, target) is False
    assert matches({"ip_cidr": ["10.0.0.0/8"]}, {"domain": "x"}) is False
    assert matches({"ip_cidr": ["10.0.0.0/8"]}, {"ip": "not-an-ip"}) is False
    assert matches({"port": [443]}, target) is True
    assert matches({"port": [80]}, target) is False
    assert matches({"port": [443]}, {"domain": "x"}) is False
    assert matches({"source_port": [443]}, target) is True
    assert matches({"source_port": [1]}, target) is False
    assert matches({"source_port": [443]}, {"port": 443}) is False
    assert matches({"network": ["tcp"]}, target) is True
    assert matches({"network": ["udp"]}, target) is False
    assert matches({"network": ["tcp"]}, {"domain": "x"}) is False
    assert matches({"protocol": ["tls"]}, target) is True
    assert matches({"protocol": ["http"]}, target) is False
    assert matches({"protocol": ["tls"]}, {"domain": "x"}) is False
    assert matches({"process_name": ["curl"]}, target) is True
    assert matches({"process_name": ["wget"]}, target) is False
    assert matches({"process_name": ["curl"]}, {"domain": "x"}) is False
    assert matches({}, target) is False


def test_evaluate_first_match_and_disabled() -> None:
    rules = [
        {"enabled": False, "match": {"domain": ["a"]}, "action": "block"},
        {"enabled": True, "match": {"domain_suffix": [".com"]}, "action": "direct"},
        {"enabled": True, "match": {"domain": ["a"]}, "action": "block"},
    ]
    result = evaluate(rules, {"domain": "a.com"})
    assert result["matched"] is True
    assert result["rule"]["action"] == "direct"
    assert evaluate([], {"domain": "a.com"}) == {"matched": False, "action": "proxy"}


def test_rule_set_update_and_serialization(tmp_path: Path) -> None:
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
            rule_set = RuleSet(name="ads", url="https://example.com/ads.srs", format="binary")
            session.add(rule_set)
            await session.commit()
            cached = settings.paths.rulesets_dir / f"{rule_set.id}.srs"
            cached.write_bytes(b"cached")
            rule_set.path = str(cached)

            with respx.mock:
                respx.get("https://example.com/ads.srs").mock(return_value=httpx.Response(304))
                result = await update_rule_set(session, settings, rule_set)
            assert result == {"updated": False, "reason": "not_modified"}
            assert rule_set.updated_at is not None

            rule_set.etag = '"v1"'
            with respx.mock:
                route = respx.get("https://example.com/ads.srs").mock(
                    return_value=httpx.Response(200, content=b"rules", headers={"etag": '"v2"'})
                )
                result = await update_rule_set(session, settings, rule_set)
            assert result["updated"] is True
            assert route.calls[0].request.headers["If-None-Match"] == '"v1"'
            assert rule_set.sha256
            assert serialize_rule_set(rule_set)["updated_at"]

            with respx.mock:
                respx.get("https://example.com/ads.srs").mock(
                    return_value=httpx.Response(500, text="down")
                )
                result = await update_rule_set(session, settings, rule_set)
            assert result["updated"] is False
            assert rule_set.last_error

            assert Path(str(rule_set.path)).name == f"{rule_set.id}.srs"
            assert Path(str(rule_set.path)).is_file()
            assert path_for(settings, "missing") is None
            assert path_for(settings, "../../etc/passwd") is None
        await engine.dispose()

    asyncio.run(_run())
