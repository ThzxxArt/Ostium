"""Rule matching and remote rule-set updates."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.config import Settings
from ostium.db.models import RuleSet
from ostium.util.time import utcnow


def matches(match: dict[str, Any], target: dict[str, Any]) -> bool:
    domain = str(target.get("domain") or "").lower()
    ip = target.get("ip")
    port = target.get("port")
    network = target.get("network")
    process = target.get("process_name")
    if values := match.get("domain"):
        if domain not in [str(item).lower() for item in values]:
            return False
    if values := match.get("domain_suffix"):
        if not any(domain.endswith(str(item).lower()) for item in values):
            return False
    if values := match.get("domain_keyword"):
        if not any(str(item).lower() in domain for item in values):
            return False
    if values := match.get("domain_regex"):
        if not any(_regex(item).search(domain) for item in values):
            return False
    if values := match.get("ip_cidr"):
        if not ip:
            return False
        try:
            address = ipaddress.ip_address(str(ip))
        except ValueError:
            return False
        if not any(address in ipaddress.ip_network(str(item), strict=False) for item in values):
            return False
    if values := match.get("port"):
        if port is None or int(port) not in [int(item) for item in values]:
            return False
    if values := match.get("source_port"):
        if port is None or int(port) not in [int(item) for item in values]:
            return False
    if values := match.get("network"):
        if network is None or str(network) not in [str(item) for item in values]:
            return False
    if values := match.get("process_name"):
        if process is None or str(process) not in [str(item) for item in values]:
            return False
    return bool(match)


def _regex(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return re.compile(r"$^")


def evaluate(rules: list[dict[str, Any]], target: dict[str, Any]) -> dict[str, Any]:
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        if matches(rule.get("match", {}), target):
            return {"matched": True, "rule": rule}
    return {"matched": False, "action": "proxy"}


async def update_rule_set(
    session: AsyncSession, settings: Settings, rule_set: RuleSet
) -> dict[str, Any]:
    target_dir = settings.paths.rulesets_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{rule_set.name}.srs"
    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            trust_env=False,
            headers={"User-Agent": "Ostium/0.1"},
        ) as client:
            headers = {}
            if rule_set.etag:
                headers["If-None-Match"] = rule_set.etag
            response = await client.get(rule_set.url, headers=headers)
            if response.status_code == 304:
                rule_set.updated_at = utcnow()
                await session.flush()
                return {"updated": False, "reason": "not_modified"}
            response.raise_for_status()
        payload = response.content
        digest = hashlib.sha256(payload).hexdigest()
        temp = target.with_suffix(".srs.tmp")
        temp.write_bytes(payload)
        temp.replace(target)
        rule_set.path = str(target)
        rule_set.sha256 = digest
        rule_set.etag = response.headers.get("etag")
        rule_set.updated_at = utcnow()
        rule_set.last_error = None
        await session.flush()
        return {"updated": True, "sha256": digest, "size": len(payload)}
    except httpx.HTTPError as exc:
        rule_set.last_error = str(exc)[:500]
        await session.flush()
        return {"updated": False, "error": str(exc)}


def serialize_rule_set(rule_set: RuleSet) -> dict[str, Any]:
    return {
        "id": rule_set.id,
        "name": rule_set.name,
        "url": rule_set.url,
        "format": rule_set.format,
        "enabled": rule_set.enabled,
        "path": rule_set.path,
        "sha256": rule_set.sha256,
        "updated_at": rule_set.updated_at.isoformat() if rule_set.updated_at else None,
        "last_error": rule_set.last_error,
    }


def path_for(settings: Settings, name: str) -> Path | None:
    candidate = settings.paths.rulesets_dir / f"{name}.srs"
    return candidate if candidate.is_file() else None
