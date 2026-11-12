"""Authentication, sessions, TOTP and login throttling."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.config import Settings
from ostium.db.models import AdminUser, ApiToken, Session
from ostium.services.crypto import SecretStore
from ostium.util.ids import new_id
from ostium.util.security import (
    constant_time_equal,
    generate_recovery_codes,
    generate_session_token,
    generate_totp_secret,
    hash_password,
    hash_recovery_codes,
    hash_token,
    totp_uri,
    verify_password,
    verify_totp,
)
from ostium.util.security import (
    consume_recovery_code as _consume_recovery_code,
)
from ostium.util.time import as_utc, utcnow

SESSION_IDLE_SECONDS = 12 * 3600
SESSION_ABSOLUTE_SECONDS = 7 * 24 * 3600
MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60

# In-process activity clock.  Session last_seen is persisted at login; keeping
# subsequent activity in memory avoids a write on every API request, which is
# important for SQLite WAL under a dashboard's parallel fetches.  A restart
# makes the idle window stricter (counted from the last persisted activity).
ACTIVITY: dict[str, float] = {}


class AuthError(Exception):
    def __init__(
        self, message: str, code: str = "invalid_credentials", status_code: int = 401
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class LoginLimiter:
    failures: dict[str, tuple[int, float]]
    window: int = LOCK_SECONDS

    def __init__(self) -> None:
        self.failures = {}

    def key(self, ip: str, username: str) -> str:
        return f"{ip}|{username.lower()}"

    def check(self, ip: str, username: str) -> None:
        record = self.failures.get(self.key(ip, username))
        if record and record[0] >= MAX_FAILURES and time.monotonic() < record[1]:
            raise AuthError("too many failed attempts; try again later", "rate_limited", 429)

    def fail(self, ip: str, username: str) -> None:
        key = self.key(ip, username)
        count, _ = self.failures.get(key, (0, 0.0))
        self.failures[key] = (count + 1, time.monotonic() + LOCK_SECONDS)

    def success(self, ip: str, username: str) -> None:
        self.failures.pop(self.key(ip, username), None)


LIMITER = LoginLimiter()


async def get_admin(session: AsyncSession) -> AdminUser | None:
    return (await session.execute(select(AdminUser).limit(1))).scalar_one_or_none()


async def create_admin(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    must_change_password: bool = False,
) -> AdminUser:
    admin = AdminUser(
        username=username.strip(),
        password_hash=hash_password(password),
        must_change_password=must_change_password,
    )
    session.add(admin)
    await session.flush()
    return admin


async def authenticate(
    session: AsyncSession,
    settings: Settings,
    *,
    username: str,
    password: str,
    totp_code: str | None,
    ip: str,
    recovery_code: str | None = None,
) -> AdminUser:
    LIMITER.check(ip, username)
    admin = await get_admin(session)
    if admin is None or admin.username.lower() != username.strip().lower():
        LIMITER.fail(ip, username)
        raise AuthError("invalid username or password")
    if admin.disabled:
        LIMITER.fail(ip, username)
        raise AuthError("this account is disabled", "account_disabled", 403)
    if admin.locked_until is not None and as_utc(admin.locked_until) > utcnow():
        raise AuthError("account temporarily locked", "account_locked", 423)
    if not verify_password(password, admin.password_hash):
        admin.failed_attempts += 1
        if admin.failed_attempts >= MAX_FAILURES:
            admin.locked_until = utcnow() + timedelta(seconds=LOCK_SECONDS)
            admin.failed_attempts = 0
        LIMITER.fail(ip, username)
        await session.flush()
        raise AuthError("invalid username or password")
    secret = None
    if admin.totp_secret_enc:
        secret = _decrypt_totp(admin, settings)
    if secret and not verify_totp(secret, totp_code or ""):
        if not recovery_code or not consume_recovery_code(admin, recovery_code):
            LIMITER.fail(ip, username)
            raise AuthError("a valid TOTP code is required", "totp_required", 401)
    admin.failed_attempts = 0
    admin.locked_until = None
    admin.last_login_at = utcnow()
    LIMITER.success(ip, username)
    await session.flush()
    return admin


def _decrypt_totp(admin: AdminUser, settings: Settings) -> str:
    store = SecretStore.from_data_dir(settings.data_dir)
    assert admin.totp_secret_enc is not None
    return store.decrypt(
        admin.totp_secret_enc, table="admin_users", record_id=admin.id, field="totp_secret"
    )


async def create_session(
    session: AsyncSession, admin: AdminUser, *, ip: str, user_agent: str
) -> tuple[str, Session]:
    token = generate_session_token()
    row = Session(
        token_hash=hash_token(token),
        admin_id=admin.id,
        ip=ip[:64],
        user_agent=user_agent[:255],
        expires_at=utcnow() + timedelta(seconds=SESSION_ABSOLUTE_SECONDS),
    )
    session.add(row)
    await session.flush()
    return token, row


async def resolve_session(session: AsyncSession, token: str) -> tuple[AdminUser, Session] | None:
    digest = hash_token(token)
    row = (
        await session.execute(select(Session).where(Session.token_hash == digest))
    ).scalar_one_or_none()
    if row is None or row.revoked:
        return None
    now = utcnow()
    if as_utc(row.expires_at) <= now:
        row.revoked = True
        await session.flush()
        return None
    idle_limit = (
        max(
            as_utc(row.last_seen_at).timestamp(),
            ACTIVITY.get(row.id, 0.0),
        )
        + SESSION_IDLE_SECONDS
    )
    if now.timestamp() > idle_limit:
        row.revoked = True
        ACTIVITY.pop(row.id, None)
        await session.flush()
        return None
    admin = await session.get(AdminUser, row.admin_id)
    if admin is None or admin.disabled:
        return None
    ACTIVITY[row.id] = now.timestamp()
    return admin, row


async def revoke_session(session: AsyncSession, row: Session) -> None:
    row.revoked = True
    ACTIVITY.pop(row.id, None)
    await session.flush()


async def set_password(session: AsyncSession, admin: AdminUser, password: str) -> None:
    admin.password_hash = hash_password(password)
    admin.must_change_password = False
    await session.flush()


async def check_password(admin: AdminUser, password: str) -> bool:
    return verify_password(password, admin.password_hash)


def start_totp(admin: AdminUser, settings: Settings) -> tuple[str, str, list[str]]:
    secret = generate_totp_secret()
    store = SecretStore.from_data_dir(settings.data_dir)
    admin.totp_secret_enc = store.encrypt(
        secret, table="admin_users", record_id=admin.id, field="totp_secret"
    )
    codes = generate_recovery_codes()
    admin.recovery_codes_hash = hash_recovery_codes(codes)
    return secret, totp_uri(secret, admin.username), codes


def confirm_totp(admin: AdminUser, settings: Settings, code: str) -> None:
    if not admin.totp_secret_enc:
        raise AuthError("TOTP setup has not started", "totp_not_started", 400)
    secret = _decrypt_totp(admin, settings)
    if not verify_totp(secret, code):
        raise AuthError("the TOTP code is not valid", "totp_invalid", 400)


async def disable_totp(session: AsyncSession, admin: AdminUser) -> None:
    admin.totp_secret_enc = None
    admin.recovery_codes_hash = []
    await session.flush()


async def create_api_token(
    session: AsyncSession, *, name: str, scopes: Sequence[str], expires_at: datetime | None = None
) -> tuple[str, ApiToken]:
    token = f"ost_{generate_session_token()}"
    row = ApiToken(
        name=name, token_hash=hash_token(token), scopes=list(scopes), expires_at=expires_at
    )
    session.add(row)
    await session.flush()
    return token, row


async def resolve_api_token(session: AsyncSession, token: str) -> ApiToken | None:
    row = (
        await session.execute(select(ApiToken).where(ApiToken.token_hash == hash_token(token)))
    ).scalar_one_or_none()
    if row is None or row.revoked:
        return None
    if row.expires_at is not None and as_utc(row.expires_at) <= utcnow():
        return None
    row.last_used_at = utcnow()
    return row


async def rotate_session_token(session: AsyncSession, row: Session) -> str:
    token = generate_session_token()
    row.token_hash = hash_token(token)
    row.last_seen_at = utcnow()
    await session.flush()
    return token


def verify_recovery(admin: AdminUser, code: str) -> bool:
    candidate = hash_token(code.replace("-", "").lower())
    return any(constant_time_equal(item, candidate) for item in admin.recovery_codes_hash)


def consume_recovery_code(admin: AdminUser, code: str) -> bool:
    """Validate and atomically remove a single-use recovery code."""

    matched, remaining = _consume_recovery_code(admin.recovery_codes_hash, code)
    if not matched:
        return False
    # Reassign so SQLAlchemy detects the JSON mutation.
    admin.recovery_codes_hash = remaining
    return True


def new_id_for_tests() -> str:
    return new_id()


LOCAL_LOGIN_TTL = 300


def make_local_login_token(settings: Settings) -> str:
    """Create a short-lived signed token for ``ostium open``.

    The token is bound to the master key, valid for five minutes and only used
    from the local CLI.  It is a GET-only convenience; no admin password is
    embedded.
    """

    from ostium.util.security import load_or_create_master_key

    key = load_or_create_master_key(settings.paths.master_key_path)
    payload = f"{int(time.time()) + LOCAL_LOGIN_TTL}:{secrets.token_urlsafe(16)}"
    signature = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload.encode() + b"." + signature).decode().rstrip("=")


def verify_local_login_token(settings: Settings, token: str) -> bool:
    from ostium.util.security import load_or_create_master_key

    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except Exception:
        return False
    # The signature is raw binary and may itself contain 0x2e (b"."), so a
    # delimiter split is ambiguous.  It is always the final 32 bytes; the
    # payload is everything before it and must end with the separator byte.
    if len(raw) <= 32:
        return False
    payload_bytes, signature = raw[:-32], raw[-32:]
    if not payload_bytes.endswith(b"."):
        return False
    payload_bytes = payload_bytes[:-1]
    try:
        payload = payload_bytes.decode("utf-8")
        expiry_text, _nonce = payload.split(":", 1)
        expiry = int(expiry_text)
    except (ValueError, UnicodeDecodeError):
        return False
    if expiry < int(time.time()):
        return False
    key = load_or_create_master_key(settings.paths.master_key_path)
    expected = hmac.new(key, payload_bytes, hashlib.sha256).digest()
    return hmac.compare_digest(signature, expected)
