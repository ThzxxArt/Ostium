"""Client profile import, refresh and endpoint extraction."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import yaml
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.db.models import Profile
from ostium.domain.endpoints import Endpoint, ProfileDocument, Protocol, TLSConfig
from ostium.services.crypto import SecretStore
from ostium.util.time import iso, utcnow


class ProfileError(Exception):
    def __init__(self, message: str, code: str = "profile_error", status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


MAX_SUBSCRIPTION_BYTES = 2 * 1024 * 1024
MAX_SUBSCRIPTION_ENDPOINTS = 500


def parse_subscription_text(text: str) -> list[Endpoint]:
    stripped = text.strip()
    if not stripped:
        raise ProfileError("the subscription is empty")
    if len(stripped.encode("utf-8")) > MAX_SUBSCRIPTION_BYTES:
        raise ProfileError("the subscription exceeds the 2 MiB size limit")
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ProfileError("invalid JSON subscription") from exc
        if isinstance(payload, dict) and "endpoints" in payload:
            try:
                return _limit(ProfileDocument.model_validate(payload).endpoints)
            except ValidationError as exc:
                raise ProfileError("invalid Ostium profile subscription") from exc
        if isinstance(payload, dict) and "outbounds" in payload:
            try:
                return _limit(_from_singbox_outbounds(payload["outbounds"]))
            except (ValidationError, TypeError, ValueError) as exc:
                raise ProfileError("invalid sing-box subscription") from exc
        raise ProfileError("JSON subscription does not contain endpoints or outbounds")
    if stripped.startswith("proxies:") or "\nproxies:" in stripped:
        try:
            return _limit(_from_clash(stripped))
        except (TypeError, ValueError) as exc:
            raise ProfileError("invalid Clash subscription") from exc
    decoded = _maybe_base64(stripped)
    if decoded is not None and "://" in decoded:
        stripped = decoded
    endpoints = []
    invalid: list[str] = []
    for number, line in enumerate(stripped.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "://" not in line:
            continue
        try:
            endpoints.append(Endpoint.from_uri(line))
        except ValueError as exc:
            invalid.append(f"line {number}: {exc}")
    if invalid:
        preview = "; ".join(invalid[:5])
        raise ProfileError(f"the subscription contains unsupported entries: {preview}")
    if not endpoints:
        raise ProfileError("no supported proxy URI was found")
    return _limit(endpoints)


def _limit(endpoints: list[Endpoint]) -> list[Endpoint]:
    if len(endpoints) > MAX_SUBSCRIPTION_ENDPOINTS:
        raise ProfileError(
            f"the subscription contains more than {MAX_SUBSCRIPTION_ENDPOINTS} endpoints"
        )
    return endpoints


def _maybe_base64(value: str) -> str | None:
    if any(ch.isspace() for ch in value.strip()) and "://" not in value:
        compact = "".join(value.split())
    else:
        compact = value.strip()
    if "://" in compact:
        return None
    padded = compact + "=" * (-len(compact) % 4)
    try:
        decoded = base64.b64decode(padded, validate=True).decode("utf-8")
    except Exception:
        return None
    return decoded


def _from_clash(text: str) -> list[Endpoint]:
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ProfileError("invalid Clash YAML") from exc
    endpoints: list[Endpoint] = []
    for index, proxy in enumerate(
        document.get("proxies", []) if isinstance(document, dict) else []
    ):
        if not isinstance(proxy, dict):
            continue
        kind = proxy.get("type")
        name = str(proxy.get("name") or f"Imported {index + 1}")
        server = str(proxy.get("server") or "")
        port = int(proxy.get("port") or 0)
        if not server or not port:
            continue
        if kind == "vless":
            reality = proxy.get("reality-opts") or {}
            endpoints.append(
                Endpoint(
                    tag=_tag(name, index),
                    protocol=Protocol.VLESS_REALITY,
                    name=name,
                    server=server,
                    port=port,
                    uuid=proxy.get("uuid"),
                    flow=proxy.get("flow") or "xtls-rprx-vision",
                    tls=TLSConfig(
                        server_name=proxy.get("servername") or proxy.get("sni"),
                        reality_public_key=reality.get("public-key"),
                        reality_short_id=reality.get("short-id"),
                        fingerprint=proxy.get("client-fingerprint", "chrome"),
                    ),
                )
            )
        elif kind == "hysteria2":
            endpoints.append(
                Endpoint(
                    tag=_tag(name, index),
                    protocol=Protocol.HYSTERIA2,
                    name=name,
                    server=server,
                    port=port,
                    password=proxy.get("password"),
                    tls=TLSConfig(
                        server_name=proxy.get("sni") or proxy.get("servername"),
                        insecure=bool(proxy.get("skip-cert-verify")),
                    ),
                )
            )
        elif kind == "trojan":
            endpoints.append(
                Endpoint(
                    tag=_tag(name, index),
                    protocol=Protocol.TROJAN,
                    name=name,
                    server=server,
                    port=port,
                    password=proxy.get("password"),
                    tls=TLSConfig(
                        server_name=proxy.get("sni") or proxy.get("servername"),
                        insecure=bool(proxy.get("skip-cert-verify")),
                    ),
                )
            )
        elif kind == "ss":
            endpoints.append(
                Endpoint(
                    tag=_tag(name, index),
                    protocol=Protocol.SHADOWSOCKS,
                    name=name,
                    server=server,
                    port=port,
                    method=str(proxy.get("cipher") or "2022-blake3-aes-128-gcm"),
                    password=proxy.get("password"),
                    tls=TLSConfig(enabled=False),
                )
            )
    if not endpoints:
        raise ProfileError("no supported proxy was found in the Clash YAML")
    return endpoints


def _from_singbox_outbounds(outbounds: list[Any]) -> list[Endpoint]:
    endpoints: list[Endpoint] = []
    for index, outbound in enumerate(outbounds):
        if not isinstance(outbound, dict):
            continue
        kind = outbound.get("type")
        tag = str(outbound.get("tag") or f"imported-{index}")
        name = tag
        server = str(outbound.get("server") or "")
        port = int(outbound.get("server_port") or 0)
        tls = outbound.get("tls") or {}
        if not server or not port:
            continue
        if kind == "vless":
            reality = tls.get("reality") or {}
            endpoints.append(
                Endpoint(
                    tag=_tag(name, index),
                    protocol=Protocol.VLESS_REALITY,
                    name=name,
                    server=server,
                    port=port,
                    uuid=outbound.get("uuid"),
                    flow=outbound.get("flow") or "xtls-rprx-vision",
                    tls=TLSConfig(
                        server_name=tls.get("server_name"),
                        reality_public_key=reality.get("public_key"),
                        reality_short_id=reality.get("short_id"),
                        fingerprint=(tls.get("utls") or {}).get("fingerprint", "chrome"),
                    ),
                )
            )
        elif kind == "hysteria2":
            endpoints.append(
                Endpoint(
                    tag=_tag(name, index),
                    protocol=Protocol.HYSTERIA2,
                    name=name,
                    server=server,
                    port=port,
                    password=outbound.get("password"),
                    tls=TLSConfig(
                        server_name=tls.get("server_name"),
                        insecure=bool(tls.get("insecure")),
                    ),
                )
            )
        elif kind == "trojan":
            endpoints.append(
                Endpoint(
                    tag=_tag(name, index),
                    protocol=Protocol.TROJAN,
                    name=name,
                    server=server,
                    port=port,
                    password=outbound.get("password"),
                    tls=TLSConfig(
                        server_name=tls.get("server_name"),
                        insecure=bool(tls.get("insecure")),
                    ),
                )
            )
        elif kind == "shadowsocks":
            endpoints.append(
                Endpoint(
                    tag=_tag(name, index),
                    protocol=Protocol.SHADOWSOCKS,
                    name=name,
                    server=server,
                    port=port,
                    method=str(outbound.get("method") or "2022-blake3-aes-128-gcm"),
                    password=outbound.get("password"),
                    tls=TLSConfig(enabled=False),
                )
            )
    if not endpoints:
        raise ProfileError("no supported outbound was found")
    return endpoints


def _tag(name: str, index: int) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")[:48]
    return f"{cleaned or 'endpoint'}-{index}"


async def create_profile(
    session: AsyncSession,
    store: SecretStore,
    *,
    name: str,
    endpoints: list[Endpoint],
    kind: str = "manual",
    subscription_url: str | None = None,
) -> Profile:
    profile = Profile(name=name[:100], kind=kind, config_enc="")
    session.add(profile)
    await session.flush()
    document = ProfileDocument(name=profile.name, endpoints=endpoints, generated_at=iso(utcnow()))
    profile.config_enc = store.encrypt(
        document.to_json(), table="profiles", record_id=profile.id, field="config"
    )
    if subscription_url:
        profile.subscription_url_enc = store.encrypt(
            subscription_url, table="profiles", record_id=profile.id, field="subscription_url"
        )
    await session.flush()
    return profile


def endpoints_from_profile(profile: Profile, store: SecretStore) -> list[Endpoint]:
    try:
        raw = store.decrypt(
            profile.config_enc, table="profiles", record_id=profile.id, field="config"
        )
        return ProfileDocument.model_validate_json(raw).endpoints
    except Exception as exc:
        raise ProfileError(
            f"profile {profile.name!r} is corrupted", "profile_corrupt", 500
        ) from exc


def subscription_url_of(profile: Profile, store: SecretStore) -> str | None:
    if not profile.subscription_url_enc:
        return None
    return store.decrypt(
        profile.subscription_url_enc,
        table="profiles",
        record_id=profile.id,
        field="subscription_url",
    )


async def refresh_profile(session: AsyncSession, store: SecretStore, profile: Profile) -> int:
    url = subscription_url_of(profile, store)
    if not url:
        raise ProfileError("this profile has no subscription URL")
    from ostium.services.netguard import UnsafeUrlError, validate_remote_url

    try:
        url = validate_remote_url(url, allow_private=True)
    except UnsafeUrlError as exc:
        profile.last_refresh_error = str(exc)[:500]
        await session.flush()
        raise ProfileError(str(exc), "unsafe_url", 400) from exc
    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            trust_env=False,
            headers={"User-Agent": "Ostium/0.1"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            if len(response.content) > MAX_SUBSCRIPTION_BYTES:
                raise ProfileError("the subscription exceeds the 2 MiB size limit")
        endpoints = parse_subscription_text(response.text)
    except (httpx.HTTPError, ProfileError) as exc:
        profile.last_refresh_error = str(exc)[:500]
        await session.flush()
        raise ProfileError(f"subscription refresh failed: {exc}", "refresh_failed", 502) from exc
    document = ProfileDocument(name=profile.name, endpoints=endpoints, generated_at=iso(utcnow()))
    profile.config_enc = store.encrypt(
        document.to_json(), table="profiles", record_id=profile.id, field="config"
    )
    profile.last_refresh_at = utcnow()
    profile.last_refresh_error = None
    await session.flush()
    return len(endpoints)


async def get_active_profiles(session: AsyncSession) -> list[Profile]:
    return list(
        (
            await session.execute(
                select(Profile).where(Profile.enabled.is_(True)).order_by(Profile.sort_order)
            )
        )
        .scalars()
        .all()
    )


def serialize_profile(profile: Profile, store: SecretStore) -> dict[str, Any]:
    try:
        endpoints = endpoints_from_profile(profile, store)
    except ProfileError:
        endpoints = []
    return {
        "id": profile.id,
        "name": profile.name,
        "kind": profile.kind,
        "enabled": profile.enabled,
        "sort_order": profile.sort_order,
        "last_refresh_at": iso(profile.last_refresh_at),
        "last_refresh_error": profile.last_refresh_error,
        "selected_endpoint": profile.selected_endpoint,
        "subscription_url": subscription_url_of(profile, store),
        "endpoints": [endpoint.model_dump(mode="json") for endpoint in endpoints],
        "created_at": iso(profile.created_at),
    }
