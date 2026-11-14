"""Secret storage helpers built on the master key."""

from __future__ import annotations

from pathlib import Path

from ostium.util.security import FieldCipher


class SecretStore:
    def __init__(self, cipher: FieldCipher) -> None:
        self._cipher = cipher

    @classmethod
    def from_data_dir(cls, data_dir: Path) -> SecretStore:
        from ostium.util.security import load_or_create_master_key

        key = load_or_create_master_key(
            data_dir / "master.key", database_path=data_dir / "ostium.db"
        )
        return cls(FieldCipher(key))

    @staticmethod
    def aad(table: str, record_id: str, field: str) -> str:
        return f"ostium:v1:{table}:{record_id}:{field}"

    def encrypt(self, value: str, *, table: str, record_id: str, field: str) -> str:
        return self._cipher.encrypt(value, self.aad(table, record_id, field))

    def decrypt(self, value: str, *, table: str, record_id: str, field: str) -> str:
        return self._cipher.decrypt(value, self.aad(table, record_id, field))
