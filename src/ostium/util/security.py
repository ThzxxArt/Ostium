"""Cryptographic primitives: field encryption, tokens, passwords, TOTP.

Design notes
------------
* The master key is 32 random bytes stored in ``master.key`` (0600).
* Field encryption uses AES-256-GCM with a 12-byte nonce and caller-supplied
  associated data binding table/row/field.  Ciphertexts are self-describing:
  ``v1.<urlsafe-b64(nonce || ciphertext)>``.
* Passwords use Argon2id (64 MiB, 3 iterations, parallelism 4).
* Session/API/subscription tokens are random 32-byte secrets; only SHA-256
  digests are stored for lookup.  Reversible copies (subscription tokens) are
  additionally encrypted with the master key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Final

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_ENCRYPTION_VERSION: Final = "v1"
_NONCE_SIZE = 12
_MASTER_KEY_SIZE = 32
_PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32)


class CryptoError(Exception):
    """Raised when a key or ciphertext is invalid."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def load_or_create_master_key(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        key = path.read_bytes()
        if len(key) != _MASTER_KEY_SIZE:
            raise CryptoError(f"master key at {path} must be exactly {_MASTER_KEY_SIZE} bytes")
        _tighten(path)
        return key
    key = secrets.token_bytes(_MASTER_KEY_SIZE)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    _tighten(path)
    return key


def _tighten(path: Path) -> None:
    if os.name == "posix":
        try:
            path.chmod(0o600)
        except OSError:
            pass


class FieldCipher:
    """AES-256-GCM field cipher bound to a single master key."""

    def __init__(self, key: bytes) -> None:
        if len(key) != _MASTER_KEY_SIZE:
            raise CryptoError("field cipher key must be 32 bytes")
        self._aead = AESGCM(key)

    @classmethod
    def from_file(cls, path: Path) -> FieldCipher:
        return cls(load_or_create_master_key(path))

    def encrypt(self, plaintext: str | bytes, aad: str) -> str:
        data = plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext
        nonce = os.urandom(_NONCE_SIZE)
        ciphertext = self._aead.encrypt(nonce, data, aad.encode("utf-8"))
        return f"{_ENCRYPTION_VERSION}.{_b64encode(nonce + ciphertext)}"

    def decrypt(self, token: str, aad: str) -> str:
        try:
            version, payload = token.split(".", 1)
        except ValueError as exc:
            raise CryptoError("malformed ciphertext") from exc
        if version != _ENCRYPTION_VERSION:
            raise CryptoError(f"unsupported ciphertext version {version!r}")
        raw = _b64decode(payload)
        nonce, ciphertext = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
        try:
            return self._aead.decrypt(nonce, ciphertext, aad.encode("utf-8")).decode("utf-8")
        except Exception as exc:  # cryptography raises InvalidTag
            raise CryptoError("ciphertext authentication failed") from exc


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def hash_password(password: str) -> str:
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _PASSWORD_HASHER.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, username: str, issuer: str = "Ostium") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    if not code:
        return False
    cleaned = code.replace(" ", "").replace("-", "")
    return pyotp.TOTP(secret).verify(cleaned, valid_window=valid_window)


def generate_recovery_codes(count: int = 10) -> list[str]:
    return [
        f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}"
        for _ in range(count)
    ]


def hash_recovery_codes(codes: list[str]) -> list[str]:
    return [hash_token(code.replace("-", "").lower()) for code in codes]


def consume_recovery_code(hashes: list[str], code: str) -> tuple[bool, list[str]]:
    digest = hash_token(code.replace("-", "").lower())
    remaining = [item for item in hashes if not constant_time_equal(item, digest)]
    return (len(remaining) != len(hashes), remaining)


def derive_backup_key(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**15,
        r=8,
        p=1,
        dklen=32,
        maxmem=128 * 1024 * 1024,
    )


def encrypt_blob(data: bytes, password: str) -> bytes:
    salt = os.urandom(16)
    nonce = os.urandom(_NONCE_SIZE)
    key = derive_backup_key(password, salt)
    ciphertext = AESGCM(key).encrypt(nonce, data, b"ostium-backup-v1")
    return b"OSTB1" + salt + nonce + ciphertext


def decrypt_blob(data: bytes, password: str) -> bytes:
    if not data.startswith(b"OSTB1"):
        raise CryptoError("not an Ostium encrypted backup")
    salt = data[5:21]
    nonce = data[21:33]
    ciphertext = data[33:]
    key = derive_backup_key(password, salt)
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, b"ostium-backup-v1")
    except Exception as exc:
        raise CryptoError("backup password is wrong or the file is corrupted") from exc
