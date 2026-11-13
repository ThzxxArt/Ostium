"""Rule matching, validation and remote rule-set updates."""

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

RULE_MATCH_KEYS = {
    "domain",
    "domain_suffix",
    "domain_keyword",
    "domain_regex",
    "ip_cidr",
    "port",
    "source_port",
    "process_name",
    "rule_set",
    "network",
    "protocol",
}
RULE_SET_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_RULE_SET_BYTES = 32 * 1024 * 1024


class RuleValidationError(ValueError):
    """A rule or rule-set reference is invalid."""


def validate_rule_match(
    match: dict[str, Any], *, defined_rule_sets: set[str] | None = None
) -> dict[str, Any]:
    if not isinstance(match, dict) or not match:
        raise RuleValidationError("a rule must contain at least one match condition")
    unknown = set(match) - RULE_MATCH_KEYS
    if unknown:
        raise RuleValidationError(f"unknown match keys: {sorted(unknown)}")
    normalized: dict[str, Any] = {}
    for key, value in match.items():
        if key in {"domain", "domain_suffix", "domain_keyword", "domain_regex"}:
            values = _string_list(value, key)
            if key == "domain_regex":
                for pattern in values:
                    try:
                        re.compile(pattern)
                    except re.error as exc:
                        raise RuleValidationError(
                            f"invalid domain_regex {pattern!r}: {exc}"
                        ) from exc
            normalized[key] = values
        elif key == "ip_cidr":
            values = _string_list(value, key)
            for cidr in values:
                try:
                    ipaddress.ip_network(cidr, strict=False)
                except ValueError as exc:
                    raise RuleValidationError(f"invalid ip_cidr {cidr!r}") from exc
            normalized[key] = values
        elif key in {"port", "source_port"}:
            ports = _int_list(value, key)
            for port in ports:
                if not 1 <= port <= 65535:
                    raise RuleValidationError(f"{key} must be between 1 and 65535")
            normalized[key] = ports
        elif key == "network":
            values = _string_list(value, key)
            if any(item not in {"tcp", "udp"} for item in values):
                raise RuleValidationError("network must be tcp or udp")
            normalized[key] = values
        elif key == "rule_set":
            values = _string_list(value, key)
            if defined_rule_sets is not None:
                missing = [item for item in values if item not in defined_rule_sets]
                if missing:
                    raise RuleValidationError(f"undefined rule_set references: {missing}")
            normalized[key] = values
        else:
            normalized[key] = _string_list(value, key)
    return normalized


def _string_list(value: Any, key: str) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        raise RuleValidationError(f"{key} must be a non-empty list")
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text or len(text) > 500:
            raise RuleValidationError(f"{key} contains an empty or oversized value")
        result.append(text)
    return result


def _int_list(value: Any, key: str) -> list[int]:
    if not isinstance(value, list) or not value:
        raise RuleValidationError(f"{key} must be a non-empty list")
    try:
        return [int(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise RuleValidationError(f"{key} must contain integers") from exc


def validate_rule_set_name(name: str) -> str:
    value = name.strip()
    if not RULE_SET_NAME_RE.fullmatch(value) or value in {".", ".."}:
        raise RuleValidationError(
            "rule set names may only contain letters, digits, dot, dash and underscore"
        )
    return value


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
    target_dir = (settings.paths.rulesets_dir / f"{rule_set.id}.srs").resolve()
    root = settings.paths.rulesets_dir.resolve()
    try:
        target_dir.relative_to(root)
    except ValueError as exc:
        raise RuleValidationError("rule set path escapes the rules directory") from exc
    root.mkdir(parents=True, exist_ok=True)
    target = target_dir
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
        if len(payload) > MAX_RULE_SET_BYTES:
            rule_set.last_error = "rule set exceeds the 32 MiB size limit"
            await session.flush()
            return {"updated": False, "error": rule_set.last_error}
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
    try:
        safe = validate_rule_set_name(name)
    except RuleValidationError:
        return None
    root = settings.paths.rulesets_dir.resolve()
    candidate = (root / f"{safe}.srs").resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None
