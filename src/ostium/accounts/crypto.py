"""AES-256-GCM field encryption.

Ciphertexts are bound to ``app.model:pk:field`` so a value copied to another
row or column fails authentication. Keys are supplied through
``OSTIUM_FIELD_KEY`` and never stored in the database.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_VERSION = "v1"
_NONCE_BYTES = 12


def _key() -> bytes:
    raw = base64.b64decode(settings.OSTIUM_FIELD_KEY)
    if len(raw) != 32:
        raise ImproperlyConfigured("OSTIUM_FIELD_KEY must decode to 32 bytes.")
    return raw


def aad(instance: Any, field: str) -> bytes:
    pk = getattr(instance, "pk", None)
    if not pk:
        raise ValueError("Encrypted fields require a persisted primary key.")
    meta = instance._meta
    return f"{meta.app_label}.{meta.model_name}:{pk}:{field}".encode()


def encrypt(value: str, associated_data: bytes) -> str:
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_key()).encrypt(nonce, value.encode("utf-8"), associated_data)
    return f"{_VERSION}:{base64.urlsafe_b64encode(nonce + ciphertext).decode('ascii')}"


def decrypt(payload: str, associated_data: bytes) -> str:
    version, _, encoded = payload.partition(":")
    if version != _VERSION or not encoded:
        raise ValueError("Unsupported ciphertext version.")
    blob = base64.urlsafe_b64decode(encoded.encode("ascii"))
    nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    return AESGCM(_key()).decrypt(nonce, ciphertext, associated_data).decode("utf-8")


def encrypt_text(instance: Any, field: str, value: str) -> str:
    return encrypt(value, aad(instance, field))


def decrypt_text(instance: Any, field: str, payload: str) -> str:
    return decrypt(payload, aad(instance, field))


def encrypt_json(instance: Any, field: str, value: dict[str, Any]) -> str:
    return encrypt_text(instance, field, json.dumps(value, sort_keys=True, separators=(",", ":")))


def decrypt_json(instance: Any, field: str, payload: str) -> dict[str, Any]:
    return json.loads(decrypt_text(instance, field, payload))
