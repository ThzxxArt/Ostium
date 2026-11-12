"""Encrypted backup and restore.

A backup contains the SQLite database, ``master.key``, ``config.toml``, the
certificate directory and a manifest.  It never contains the sing-box binary or
logs.  Encrypted backups use the ``OSTB1`` container (scrypt + AES-256-GCM).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from ostium import __version__
from ostium.config import Settings
from ostium.util.security import decrypt_blob, encrypt_blob
from ostium.util.time import iso, utcnow

BACKUP_PREFIX = "ostium-backup-"
ALLOWED_MEMBERS = {"ostium.db", "master.key", "config.toml", "manifest.json"}


class BackupError(Exception):
    def __init__(self, message: str, code: str = "backup_error", status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def create_backup(
    settings: Settings,
    *,
    password: str | None = None,
    include_master_key: bool = True,
) -> dict[str, Any]:
    paths = settings.paths
    paths.backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    encrypted = bool(password)
    filename = f"{BACKUP_PREFIX}{stamp}.{'ostb' if encrypted else 'tar.gz'}"
    target = paths.backups_dir / filename
    if target.exists():
        raise BackupError("a backup with the same timestamp already exists", "exists", 409)
    with tempfile.TemporaryDirectory(prefix="ostium-backup-") as temp:
        temp_path = Path(temp)
        db_copy = temp_path / "ostium.db"
        _sqlite_backup(paths.db_path, db_copy)
        manifest = {
            "format": "ostium-backup",
            "version": 1,
            "app_version": __version__,
            "created_at": iso(utcnow()),
            "role": settings.role.value,
            "encrypted": encrypted,
        }
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            archive.add(db_copy, arcname="ostium.db")
            if include_master_key and paths.master_key_path.is_file():
                archive.add(paths.master_key_path, arcname="master.key")
            if paths.config_file.is_file():
                archive.add(paths.config_file, arcname="config.toml")
            if paths.certs_dir.is_dir():
                for item in paths.certs_dir.rglob("*"):
                    if item.is_file():
                        archive.add(
                            item, arcname=str(Path("certs") / item.relative_to(paths.certs_dir))
                        )
            manifest_bytes = json.dumps(manifest, indent=2).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(manifest_bytes)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(manifest_bytes))
        raw = buffer.getvalue()
    payload = encrypt_blob(raw, password) if password else raw
    target.write_bytes(payload)
    if os.name == "posix":
        target.chmod(0o600)
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "filename": filename,
        "path": str(target),
        "size": len(payload),
        "sha256": digest,
        "encrypted": encrypted,
        "created_at": iso(utcnow()),
    }


def _sqlite_backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise BackupError("the Ostium database does not exist", "no_database", 404)
    src = sqlite3.connect(source)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def restore_backup(
    settings: Settings,
    backup_path: Path,
    *,
    password: str | None = None,
    include_master_key: bool = True,
) -> dict[str, Any]:
    if not backup_path.is_file():
        raise BackupError("backup file not found", "not_found", 404)
    raw = backup_path.read_bytes()
    if raw.startswith(b"OSTB1"):
        if not password:
            raise BackupError(
                "this backup is encrypted; a password is required", "password_required"
            )
        raw = decrypt_blob(raw, password)
    with tempfile.TemporaryDirectory(prefix="ostium-restore-") as temp:
        staging = Path(temp)
        try:
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
                _safe_extract(archive, staging)
        except (tarfile.TarError, OSError) as exc:
            raise BackupError(f"backup archive is invalid: {exc}", "invalid_archive") from exc
        manifest_path = staging / "manifest.json"
        if not manifest_path.is_file():
            raise BackupError("backup is missing its manifest", "invalid_archive")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") != "ostium-backup":
            raise BackupError("not an Ostium backup", "invalid_archive")
        if not (staging / "ostium.db").is_file():
            raise BackupError("backup does not contain a database", "invalid_archive")
        paths = settings.paths
        paths.ensure()
        db_target = paths.db_path
        wal = paths.data_dir / "ostium.db-wal"
        shm = paths.data_dir / "ostium.db-shm"
        for leftover in (wal, shm):
            leftover.unlink(missing_ok=True)
        shutil.copy2(staging / "ostium.db", db_target)
        if os.name == "posix":
            db_target.chmod(0o600)
        if include_master_key and (staging / "master.key").is_file():
            shutil.copy2(staging / "master.key", paths.master_key_path)
            if os.name == "posix":
                paths.master_key_path.chmod(0o600)
        if (staging / "config.toml").is_file():
            paths.config_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staging / "config.toml", paths.config_file)
        certs = staging / "certs"
        if certs.is_dir():
            for item in certs.rglob("*"):
                if item.is_file():
                    relative = item.relative_to(certs)
                    destination = (paths.certs_dir / relative).resolve()
                    try:
                        destination.relative_to(paths.certs_dir.resolve())
                    except ValueError as exc:
                        raise BackupError(
                            "backup contains an unsafe certificate path", "invalid_archive"
                        ) from exc
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, destination)
        return {
            "restored": True,
            "app_version": manifest.get("app_version"),
            "created_at": manifest.get("created_at"),
            "restart_required": True,
        }


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    for member in archive.getmembers():
        name = member.name.lstrip("./")
        if member.isdir():
            continue
        if not member.isfile():
            raise BackupError("backup contains a non-regular file", "invalid_archive")
        top = name.split("/", 1)[0]
        if name not in ALLOWED_MEMBERS and top != "certs":
            raise BackupError(f"backup contains an unexpected entry: {name}", "invalid_archive")
        if ".." in Path(name).parts or Path(name).is_absolute():
            raise BackupError("backup contains an unsafe path", "invalid_archive")
    archive.extractall(destination, filter="data")


def backup_record(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "filename": payload["filename"],
        "size": payload["size"],
        "sha256": payload["sha256"],
        "encrypted": payload["encrypted"],
        "created_at": payload["created_at"],
    }


def stage_restore(
    settings: Settings, backup_path: Path, *, password: str | None = None
) -> dict[str, Any]:
    """Stage a restore to be applied before the next database open."""

    from ostium.services.crypto import SecretStore

    if not backup_path.is_file():
        raise BackupError("backup file not found", "not_found", 404)
    raw = backup_path.read_bytes()
    encrypted = raw.startswith(b"OSTB1")
    if encrypted and not password:
        raise BackupError("this backup is encrypted; a password is required", "password_required")
    store = SecretStore.from_data_dir(settings.data_dir)
    password_token = (
        store.encrypt(password, table="settings", record_id="restore", field="password")
        if password
        else None
    )
    paths = settings.paths
    payload_path = paths.backups_dir / "restore-pending.bin"
    metadata_path = paths.backups_dir / "restore-pending.json"
    payload_path.write_bytes(raw)
    metadata_path.write_text(
        json.dumps(
            {
                "filename": backup_path.name,
                "encrypted": encrypted,
                "password_enc": password_token,
                "staged_at": iso(utcnow()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    for path in (payload_path, metadata_path):
        if os.name == "posix":
            path.chmod(0o600)
    return {"staged": True, "encrypted": encrypted, "filename": backup_path.name}


def apply_pending_restore(settings: Settings) -> dict[str, Any] | None:
    """Apply a staged restore before the app opens the database."""

    from ostium.services.crypto import SecretStore

    paths = settings.paths
    payload_path = paths.backups_dir / "restore-pending.bin"
    metadata_path = paths.backups_dir / "restore-pending.json"
    if not payload_path.is_file() or not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        password = None
        if metadata.get("password_enc"):
            store = SecretStore.from_data_dir(settings.data_dir)
            password = store.decrypt(
                metadata["password_enc"], table="settings", record_id="restore", field="password"
            )
        result = restore_backup(settings, payload_path, password=password)
        result["filename"] = metadata.get("filename")
        return result
    finally:
        payload_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
