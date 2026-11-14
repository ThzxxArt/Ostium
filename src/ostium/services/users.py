"""Proxy-user lifecycle, credentials, quota fields and endpoint projection."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.db.models import Certificate, Inbound, ProxyUser
from ostium.domain.endpoints import Endpoint, Protocol, TLSConfig
from ostium.services.crypto import SecretStore
from ostium.util.ids import new_short_id, new_ss2022_key, new_token, new_uuid
from ostium.util.security import hash_token
from ostium.util.time import as_utc, iso, utcnow

USER_FIELDS = ("password", "ss_password", "subscription_token")


class UserError(Exception):
    def __init__(self, message: str, code: str = "user_error", status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


async def create_user(
    session: AsyncSession,
    store: SecretStore,
    *,
    name: str,
    expires_at: datetime | None = None,
    quota_bytes: int = 0,
    quota_cycle: str = "total",
    note: str = "",
) -> tuple[ProxyUser, str, str]:
    name = name.strip()
    if not name or len(name) > 64 or any(ch in name for ch in "<>\"'\\\n\r"):
        raise UserError("user name must be 1-64 characters without < > quotes or slashes")
    if quota_cycle not in {"total", "monthly"}:
        raise UserError("quota cycle must be 'total' or 'monthly'")
    if quota_bytes < 0:
        raise UserError("quota must be zero or positive")
    user = ProxyUser(
        name=name,
        uuid=new_uuid(),
        password_enc="",
        ss_password_enc="",
        expires_at=expires_at,
        quota_bytes=quota_bytes,
        quota_cycle=quota_cycle,
        cycle_started_at=utcnow(),
        note=note[:500],
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise UserError("a user with this name already exists", "name_taken", 409) from exc
    _write_credentials(user, store, new_token(24), new_ss2022_key())
    token = new_token(32)
    user.subscription_token_hash = hash_token(token)
    user.subscription_token_enc = store.encrypt(
        token, table="proxy_users", record_id=user.id, field="subscription_token"
    )
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise UserError("a user with this name already exists", "name_taken", 409) from exc
    return user, decrypt_password(user, store), token


def _write_credentials(user: ProxyUser, store: SecretStore, password: str, ss_key: str) -> None:
    user.password_enc = store.encrypt(
        password, table="proxy_users", record_id=user.id, field="password"
    )
    user.ss_password_enc = store.encrypt(
        ss_key, table="proxy_users", record_id=user.id, field="ss_password"
    )


def decrypt_password(user: ProxyUser, store: SecretStore) -> str:
    return store.decrypt(
        user.password_enc, table="proxy_users", record_id=user.id, field="password"
    )


def decrypt_ss_password(user: ProxyUser, store: SecretStore) -> str:
    if not user.ss_password_enc:
        raise UserError("user has no Shadowsocks credential")
    return store.decrypt(
        user.ss_password_enc, table="proxy_users", record_id=user.id, field="ss_password"
    )


def decrypt_subscription_token(user: ProxyUser, store: SecretStore) -> str | None:
    if not user.subscription_token_enc:
        return None
    return store.decrypt(
        user.subscription_token_enc,
        table="proxy_users",
        record_id=user.id,
        field="subscription_token",
    )


async def rotate_credentials(session: AsyncSession, store: SecretStore, user: ProxyUser) -> str:
    password = new_token(24)
    _write_credentials(user, store, password, new_ss2022_key())
    user.uuid = new_uuid()
    await session.flush()
    return password


async def rotate_subscription(session: AsyncSession, store: SecretStore, user: ProxyUser) -> str:
    token = new_token(32)
    user.subscription_token_hash = hash_token(token)
    user.subscription_token_enc = store.encrypt(
        token, table="proxy_users", record_id=user.id, field="subscription_token"
    )
    await session.flush()
    return token


async def reset_usage(session: AsyncSession, user: ProxyUser) -> None:
    user.used_bytes = 0
    user.cycle_started_at = utcnow()
    if user.disabled_reason == "quota_exceeded":
        # Resetting usage is also the operator's recovery path for a user that
        # was automatically disabled at 100%: clear the reason and re-enable
        # unless the account has independently expired.
        user.disabled_reason = None
        if user.expires_at is None or as_utc(user.expires_at) > utcnow():
            user.enabled = True
    elif user.disabled_reason == "expired" and user.expires_at is None:
        user.disabled_reason = None
    await session.flush()


def effective_used(user: ProxyUser, pending: int = 0) -> int:
    return max(0, user.used_bytes + pending)


def status_of(user: ProxyUser, *, online: bool = False) -> str:
    if not user.enabled:
        return user.disabled_reason or "disabled"
    if user.expires_at is not None and as_utc(user.expires_at) <= utcnow():
        return "expired"
    if user.quota_bytes > 0 and user.used_bytes >= user.quota_bytes:
        return "quota_exceeded"
    return "online" if online else "active"


def serialize_user(
    user: ProxyUser, *, online: bool = False, reveal: dict[str, Any] | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": user.id,
        "name": user.name,
        "enabled": user.enabled,
        "uuid": user.uuid,
        "expires_at": iso(user.expires_at),
        "quota_bytes": user.quota_bytes,
        "quota_cycle": user.quota_cycle,
        "cycle_started_at": iso(user.cycle_started_at),
        "used_bytes": user.used_bytes,
        "note": user.note,
        "status": status_of(user, online=online),
        "online": online,
        "last_seen_at": iso(user.last_seen_at),
        "created_at": iso(user.created_at),
        "disabled_reason": user.disabled_reason,
        "has_subscription": bool(user.subscription_token_hash),
    }
    if reveal:
        data.update(reveal)
    return data


async def get_user_by_name(session: AsyncSession, name: str) -> ProxyUser | None:
    return (
        await session.execute(select(ProxyUser).where(ProxyUser.name == name))
    ).scalar_one_or_none()


async def get_user_by_subscription_token(
    session: AsyncSession, store: SecretStore, token: str
) -> ProxyUser | None:
    digest = hash_token(token)
    user = (
        await session.execute(select(ProxyUser).where(ProxyUser.subscription_token_hash == digest))
    ).scalar_one_or_none()
    if user is None:
        return None
    # Verify against the encrypted copy as a second factor against hash collisions.
    try:
        stored = decrypt_subscription_token(user, store)
    except Exception:
        return None
    return user if stored == token else None


async def ensure_inbounds(session: AsyncSession, store: SecretStore) -> list[Inbound]:
    existing = {row.kind: row for row in (await session.execute(select(Inbound))).scalars().all()}
    if "vless" not in existing:
        private_key = X25519PrivateKey.generate()
        private_raw = private_key.private_bytes_raw()
        public_raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        reality_params = {
            "private_key": base64.urlsafe_b64encode(private_raw).decode().rstrip("="),
            "public_key": base64.urlsafe_b64encode(public_raw).decode().rstrip("="),
            "short_id": new_short_id(8),
            "server_name": "www.apple.com",
            "handshake_server": "www.apple.com",
            "handshake_port": 443,
        }
        inbound = Inbound(kind="vless", enabled=True, listen="0.0.0.0", port=443)
        session.add(inbound)
        await session.flush()
        inbound.params_enc = store.encrypt(
            json.dumps(reality_params), table="inbounds", record_id=inbound.id, field="params"
        )
        existing["vless"] = inbound
    defaults = {
        "hysteria2": (443, False),
        "trojan": (443, False),
        "shadowsocks": (8388, False),
    }
    for kind, (port, enabled) in defaults.items():
        if kind not in existing:
            inbound = Inbound(kind=kind, enabled=enabled, listen="0.0.0.0", port=port)
            session.add(inbound)
            await session.flush()
            inbound_params: dict[str, Any] = {}
            if kind == "shadowsocks":
                inbound_params["server_key"] = new_ss2022_key()
            if kind == "hysteria2":
                inbound_params["obfs_password"] = None
            inbound.params_enc = store.encrypt(
                json.dumps(inbound_params), table="inbounds", record_id=inbound.id, field="params"
            )
            existing[kind] = inbound
    await session.flush()
    return list(existing.values())


def inbound_params(inbound: Inbound, store: SecretStore) -> dict[str, Any]:
    if not inbound.params_enc:
        return {}
    raw = store.decrypt(inbound.params_enc, table="inbounds", record_id=inbound.id, field="params")
    try:
        return dict(json.loads(raw))
    except json.JSONDecodeError:
        return {}


async def endpoints_for_user(
    session: AsyncSession,
    store: SecretStore,
    user: ProxyUser,
    *,
    server_host: str,
    server_name: str | None = None,
) -> list[Endpoint]:
    from ostium.services.certificates import certificate_pin_sha256

    inbounds = (await session.execute(select(Inbound))).scalars().all()
    certificates = {
        row.id: row
        for row in (await session.execute(select(Certificate))).scalars().all()
        if row.status == "ready"
        and row.expires_at is not None
        and as_utc(row.expires_at) > utcnow()
        and Path(row.cert_path).is_file()
        and Path(row.key_path).is_file()
    }
    password = decrypt_password(user, store)
    ss_user_key = decrypt_ss_password(user, store)
    endpoints: list[Endpoint] = []
    display = server_name or server_host
    for inbound in sorted(
        inbounds,
        key=lambda row: {"vless": 0, "hysteria2": 1, "trojan": 2, "shadowsocks": 3}.get(
            row.kind, 9
        ),
    ):
        if not inbound.enabled:
            continue
        params = inbound_params(inbound, store)
        cert = certificates.get(inbound.certificate_id or "")
        if inbound.kind == "vless":
            if not params.get("private_key") or not params.get("public_key"):
                continue
            endpoints.append(
                Endpoint(
                    tag=f"{user.name}-reality",
                    protocol=Protocol.VLESS_REALITY,
                    name=f"{display} · Reality",
                    server=server_host,
                    port=inbound.port,
                    uuid=user.uuid,
                    flow="xtls-rprx-vision",
                    tls=TLSConfig(
                        server_name=params.get("server_name", "www.apple.com"),
                        reality_public_key=params.get("public_key"),
                        reality_short_id=params.get("short_id"),
                        fingerprint="chrome",
                    ),
                )
            )
        elif inbound.kind == "hysteria2" and cert is not None:
            pin = certificate_pin_sha256(cert.cert_path) if cert.source == "self-signed" else None
            endpoints.append(
                Endpoint(
                    tag=f"{user.name}-hy2",
                    protocol=Protocol.HYSTERIA2,
                    name=f"{display} · Hysteria2",
                    server=server_host,
                    port=inbound.port,
                    password=password,
                    obfs_password=params.get("obfs_password"),
                    tls=TLSConfig(
                        server_name=cert.domain,
                        insecure=False,
                        certificate_pin_sha256=pin,
                    ),
                )
            )
        elif inbound.kind == "trojan" and cert is not None:
            pin = certificate_pin_sha256(cert.cert_path) if cert.source == "self-signed" else None
            endpoints.append(
                Endpoint(
                    tag=f"{user.name}-trojan",
                    protocol=Protocol.TROJAN,
                    name=f"{display} · Trojan",
                    server=server_host,
                    port=inbound.port,
                    password=password,
                    tls=TLSConfig(
                        server_name=cert.domain,
                        insecure=False,
                        certificate_pin_sha256=pin,
                    ),
                )
            )
        elif inbound.kind == "shadowsocks":
            server_key = str(params.get("server_key") or "").strip()
            # Shadowsocks 2022 multi-user outbound passwords are
            # ``server_key:user_key``.  The server inbound keeps the server key
            # and each user entry keeps only the user key.
            client_password = f"{server_key}:{ss_user_key}" if server_key else ss_user_key
            endpoints.append(
                Endpoint(
                    tag=f"{user.name}-ss2022",
                    protocol=Protocol.SHADOWSOCKS,
                    name=f"{display} · SS2022",
                    server=server_host,
                    port=inbound.port,
                    password=client_password,
                    method="2022-blake3-aes-128-gcm",
                    tls=TLSConfig(enabled=False),
                )
            )
    return endpoints


async def server_hostname(session: AsyncSession) -> str:
    from ostium.services.settings import get_setting

    server = await get_setting(session, "server", {})
    if isinstance(server, dict):
        value = server.get("public_host") or server.get("domain")
        if value:
            return str(value)
    return "127.0.0.1"
