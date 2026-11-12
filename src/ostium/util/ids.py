"""Identifier and token generation."""

from __future__ import annotations

import base64
import secrets
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


def new_token(nbytes: int = 32) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).rstrip(b"=").decode("ascii")


def new_password(nbytes: int = 24) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).rstrip(b"=").decode("ascii")


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_short_id(nbytes: int = 8) -> str:
    return secrets.token_hex(nbytes)


def new_ss2022_key() -> str:
    """16-byte base64 key for ``2022-blake3-aes-128-gcm``."""

    return base64.b64encode(secrets.token_bytes(16)).decode("ascii")
