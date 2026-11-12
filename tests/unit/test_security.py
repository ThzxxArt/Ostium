from __future__ import annotations

from pathlib import Path

import pytest

from ostium.util.security import (
    CryptoError,
    FieldCipher,
    consume_recovery_code,
    decrypt_blob,
    encrypt_blob,
    generate_recovery_codes,
    generate_session_token,
    generate_totp_secret,
    hash_password,
    hash_recovery_codes,
    hash_token,
    load_or_create_master_key,
    verify_password,
    verify_totp,
)


def test_master_key_created_0600(tmp_path: Path) -> None:
    key_path = tmp_path / "master.key"
    key = load_or_create_master_key(key_path)
    assert len(key) == 32
    assert key_path.read_bytes() == key
    assert key_path.stat().st_mode & 0o777 == 0o600
    assert load_or_create_master_key(key_path) == key


def test_field_cipher_roundtrip_and_aad(tmp_path: Path) -> None:
    cipher = FieldCipher(load_or_create_master_key(tmp_path / "master.key"))
    token = cipher.encrypt("super-secret", "proxy_users:1:password")
    assert token.startswith("v1.")
    assert cipher.decrypt(token, "proxy_users:1:password") == "super-secret"
    with pytest.raises(CryptoError):
        cipher.decrypt(token, "proxy_users:2:password")
    with pytest.raises(CryptoError):
        cipher.decrypt("garbage", "aad")


def test_password_hashing() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


def test_session_tokens_are_random_and_hashed() -> None:
    left = generate_session_token()
    right = generate_session_token()
    assert left != right
    assert hash_token(left) != hash_token(right)
    assert len(hash_token(left)) == 64


def test_totp_and_recovery_codes() -> None:
    import pyotp

    secret = generate_totp_secret()
    code = pyotp.TOTP(secret).now()
    assert verify_totp(secret, code)
    assert not verify_totp(secret, "000000")

    codes = generate_recovery_codes()
    hashes = hash_recovery_codes(codes)
    assert len(codes) == 10
    used, remaining = consume_recovery_code(hashes, codes[0])
    assert used
    assert len(remaining) == 9
    used_again, remaining_again = consume_recovery_code(remaining, codes[0])
    assert not used_again
    assert len(remaining_again) == 9


def test_backup_blob_encryption() -> None:
    payload = b"database-bytes" * 100
    encrypted = encrypt_blob(payload, "a-strong-password")
    assert encrypted.startswith(b"OSTB1")
    assert decrypt_blob(encrypted, "a-strong-password") == payload
    with pytest.raises(CryptoError):
        decrypt_blob(encrypted, "wrong-password")
    with pytest.raises(CryptoError):
        decrypt_blob(payload, "a-strong-password")
