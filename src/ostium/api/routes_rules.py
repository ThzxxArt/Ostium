"""Routing rule and rule-set endpoints."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.api.deps import Services, client_ip, get_current_admin, get_services, get_session
from ostium.api.errors import ApiError
from ostium.config import Role
from ostium.db.models import AdminUser, Rule, RuleSet
from ostium.engine.manager import EngineError
from ostium.services import rules as rule_service
from ostium.services.audit import audit

router = APIRouter(tags=["rules"])


class RuleCreate(BaseModel):
    action: Literal["proxy", "direct", "block"] = "proxy"
    match: dict[str, Any] = Field(default_factory=dict)
    note: str = Field(default="", max_length=300)
    priority: int = 100
    enabled: bool = True


class RulePatch(BaseModel):
    action: Literal["proxy", "direct", "block"] | None = None
    match: dict[str, Any] | None = None
    note: str | None = None
    priority: int | None = None
    enabled: bool | None = None


class RuleTest(BaseModel):
    domain: str | None = None
    ip: str | None = None
    port: int | None = None
    network: Literal["tcp", "udp"] | None = None
    process_name: str | None = None


class ReorderRequest(BaseModel):
    ids: list[str]


class RuleSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=1000)
    format: Literal["binary", "source"] = "binary"
    enabled: bool = True


def serialize_rule(rule: Rule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "priority": rule.priority,
        "enabled": rule.enabled,
        "action": rule.action,
        "match": rule.match_json,
        "note": rule.note,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


async def _apply_client(services: Services, session: AsyncSession) -> dict[str, Any]:
    if services.settings.role is not Role.CLIENT:
        return {
            "applied": False,
            "warning": "rules are stored; the server applies them to clients via subscriptions",
        }
    try:
        result = await services.engine.apply_client(session)
        return {"applied": True, "revision": result["status"].get("revision")}
    except EngineError as exc:
        if exc.code in {"core_unreachable", "engine_unavailable", "no_profile"}:
            return {"applied": False, "warning": str(exc)}
        raise ApiError(exc.status_code, str(exc), exc.code) from exc


@router.get("/rules")
async def list_rules(
    _: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = (
        (await session.execute(select(Rule).order_by(Rule.priority, Rule.created_at)))
        .scalars()
        .all()
    )
    return {"rules": [serialize_rule(rule) for rule in rows]}


@router.post("/rules", status_code=201)
async def add_rule(
    payload: RuleCreate,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rule = Rule(
        action=payload.action,
        match_json=payload.match,
        note=payload.note,
        priority=payload.priority,
        enabled=payload.enabled,
    )
    session.add(rule)
    await session.flush()
    applied = await _apply_client(services, session)
    await audit(
        session, actor=admin.username, action="rule.created", target=rule.id, ip=client_ip(request)
    )
    return {"rule": serialize_rule(rule), **applied}


@router.patch("/rules/{rule_id}")
async def update_rule(
    rule_id: str,
    payload: RulePatch,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rule = await session.get(Rule, rule_id)
    if rule is None:
        raise ApiError(404, "rule not found", "not_found")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("action"):
        rule.action = changes["action"]
    if "match" in changes and changes["match"] is not None:
        rule.match_json = changes["match"]
    if "note" in changes and changes["note"] is not None:
        rule.note = changes["note"]
    if "priority" in changes and changes["priority"] is not None:
        rule.priority = changes["priority"]
    if "enabled" in changes and changes["enabled"] is not None:
        rule.enabled = changes["enabled"]
    await session.flush()
    applied = await _apply_client(services, session)
    await audit(
        session,
        actor=admin.username,
        action="rule.updated",
        target=rule.id,
        ip=client_ip(request),
        detail={"fields": sorted(changes)},
    )
    return {"rule": serialize_rule(rule), **applied}


@router.delete("/rules/{rule_id}")
async def delete_rule(
    rule_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rule = await session.get(Rule, rule_id)
    if rule is None:
        raise ApiError(404, "rule not found", "not_found")
    await session.delete(rule)
    await session.flush()
    applied = await _apply_client(services, session)
    await audit(
        session, actor=admin.username, action="rule.deleted", target=rule_id, ip=client_ip(request)
    )
    return {"deleted": True, **applied}


@router.post("/rules/reorder")
async def reorder(
    payload: ReorderRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = (await session.execute(select(Rule))).scalars().all()
    by_id = {rule.id: rule for rule in rows}
    for index, rule_id in enumerate(payload.ids):
        if rule_id in by_id:
            by_id[rule_id].priority = index * 10
    await session.flush()
    applied = await _apply_client(services, session)
    await audit(session, actor=admin.username, action="rule.reordered", ip=client_ip(request))
    return {"ok": True, **applied}


@router.post("/rules/test")
async def test_rule(
    payload: RuleTest,
    _: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                select(Rule).where(Rule.enabled.is_(True)).order_by(Rule.priority, Rule.created_at)
            )
        )
        .scalars()
        .all()
    )
    rules = [
        {"id": rule.id, "action": rule.action, "match": rule.match_json, "enabled": rule.enabled}
        for rule in rows
    ]
    result = rule_service.evaluate(
        rules,
        {
            "domain": payload.domain,
            "ip": payload.ip,
            "port": payload.port,
            "network": payload.network,
            "process_name": payload.process_name,
        },
    )
    return result


@router.get("/rule-sets")
async def list_rule_sets(
    _: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = (await session.execute(select(RuleSet).order_by(RuleSet.name))).scalars().all()
    return {"rule_sets": [rule_service.serialize_rule_set(row) for row in rows]}


@router.post("/rule-sets", status_code=201)
async def add_rule_set(
    payload: RuleSetCreate,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    existing = (
        await session.execute(select(RuleSet).where(RuleSet.name == payload.name))
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError(409, "a rule set with this name already exists", "name_taken")
    rule_set = RuleSet(
        name=payload.name, url=payload.url, format=payload.format, enabled=payload.enabled
    )
    session.add(rule_set)
    await session.flush()
    await audit(
        session,
        actor=admin.username,
        action="rule_set.created",
        target=rule_set.name,
        ip=client_ip(request),
    )
    return {"rule_set": rule_service.serialize_rule_set(rule_set)}


@router.post("/rule-sets/{rule_set_id}/update")
async def update_rule_set(
    rule_set_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rule_set = await session.get(RuleSet, rule_set_id)
    if rule_set is None:
        raise ApiError(404, "rule set not found", "not_found")
    result = await rule_service.update_rule_set(session, services.settings, rule_set)
    await audit(
        session,
        actor=admin.username,
        action="rule_set.updated",
        target=rule_set.name,
        ip=client_ip(request),
        detail=result,
    )
    applied = await _apply_client(services, session)
    return {"result": result, "rule_set": rule_service.serialize_rule_set(rule_set), **applied}


@router.delete("/rule-sets/{rule_set_id}")
async def delete_rule_set(
    rule_set_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rule_set = await session.get(RuleSet, rule_set_id)
    if rule_set is None:
        raise ApiError(404, "rule set not found", "not_found")
    await session.delete(rule_set)
    await session.flush()
    applied = await _apply_client(services, session)
    await audit(
        session,
        actor=admin.username,
        action="rule_set.deleted",
        target=rule_set.name,
        ip=client_ip(request),
    )
    return {"deleted": True, **applied}
