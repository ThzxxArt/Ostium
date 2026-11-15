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
import tomllib
from pathlib import Path
from typing import Any

from ostium import __version__
from ostium.config import Settings
from ostium.util.security import CryptoError, decrypt_blob
from ostium.util.time import iso, utcnow

BACKUP_PREFIX = "ostium-backup-"
AUTO_BACKUP_PREFIX = "ostium-auto-backup-"
# Directories copied verbatim into a backup.  ``acme`` holds the encrypted
# account key; ``rulesets`` was missing in v1 and broke client restores.
BACKUP_DIRECTORIES = ("certs", "rulesets", "acme")
ALLOWED_MEMBERS = {"ostium.db", "master.key", "config.toml", "manifest.json"}
# Bound both the file read into memory and the expanded archive.  A restore
# is an admin action, but a corrupted/hostile archive must not fill the disk or
# exhaust memory.
MAX_BACKUP_FILE_BYTES = 2 * 1024 * 1024 * 1024
MAX_RESTORE_EXPANDED_BYTES = 4 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 20_000


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
    target: Path | None = None,
    automatic: bool = False,
) -> dict[str, Any]:
    paths = settings.paths
    paths.backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%d-%H%M%S-%f")
    encrypted = bool(password)
    prefix = AUTO_BACKUP_PREFIX if automatic else BACKUP_PREFIX
    filename = f"{prefix}{stamp}.{'ostb' if encrypted else 'tar.gz'}"
    if target is None:
        target = paths.backups_dir / filename
    else:
        target = target.expanduser()
        if target.is_dir():
            raise BackupError("backup output must be a file path", "invalid_target", 400)
        target.parent.mkdir(parents=True, exist_ok=True)
        filename = target.name
    if target.exists():
        raise BackupError("a backup with the same timestamp already exists", "exists", 409)
    with tempfile.TemporaryDirectory(prefix="ostium-backup-") as temp:
        temp_path = Path(temp)
        db_copy = temp_path / "ostium.db"
        _sqlite_backup(paths.db_path, db_copy)
        members: list[tuple[str, Path]] = [("ostium.db", db_copy)]
        master_key_included = bool(include_master_key and paths.master_key_path.is_file())
        if not master_key_included and _database_requires_master_key(paths.db_path):
            raise BackupError(
                "the database contains encrypted fields but master.key is missing "
                "or excluded; this backup could never be restored",
                "missing_master_key",
                409,
            )
        if master_key_included:
            members.append(("master.key", paths.master_key_path))
        if settings.config_file.is_file():
            members.append(("config.toml", settings.config_file))
        for directory_name in BACKUP_DIRECTORIES:
            directory = paths.data_dir / directory_name
            if not directory.is_dir():
                continue
            for item in directory.rglob("*"):
                if not item.is_file():
                    continue
                if item.name == "issue.lock":
                    continue
                arcname = str(Path(directory_name) / item.relative_to(directory))
                members.append((arcname, item))
        checksums = {
            arcname: _sha256_file(source) for arcname, source in members if source.is_file()
        }
        manifest = {
            "format": "ostium-backup",
            "version": 2,
            "app_version": __version__,
            "created_at": iso(utcnow()),
            "role": settings.role.value,
            "encrypted": encrypted,
            "master_key_included": master_key_included,
            "directories": list(BACKUP_DIRECTORIES),
            "checksums": checksums,
        }
        tar_path = temp_path / "backup.tar.gz"
        with tarfile.open(tar_path, mode="w:gz") as archive:
            for arcname, source in members:
                archive.add(source, arcname=arcname)
            manifest_bytes = json.dumps(manifest, indent=2).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(manifest_bytes)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(manifest_bytes))
        if tar_path.stat().st_size > MAX_BACKUP_FILE_BYTES:
            raise BackupError("backup archive exceeds the size limit", "backup_too_large", 413)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{filename}.", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            # Copy/encrypt in bounded chunks.  The previous implementation
            # built the entire tar in memory and optionally encrypted it in
            # place, so a multi-GiB data directory could exhaust the control
            # plane.  Keep the temporary output inside this temp-dir scope so
            # the tar source still exists while it is copied.
            if password:
                from ostium.util.security import encrypt_stream

                with tar_path.open("rb") as source_handle, os.fdopen(descriptor, "wb") as output:
                    encrypt_stream(source_handle, output, password)
                    output.flush()
                    os.fsync(output.fileno())
            else:
                with tar_path.open("rb") as source_handle, os.fdopen(descriptor, "wb") as output:
                    shutil.copyfileobj(source_handle, output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
            if os.name == "posix":
                temporary.chmod(0o600)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        digest = _sha256_file(target)
        size = target.stat().st_size
    return {
        "filename": filename,
        "path": str(target),
        "size": size,
        "sha256": digest,
        "encrypted": encrypted,
        "automatic": automatic,
        "created_at": iso(utcnow()),
    }


def _sqlite_backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise BackupError("the Ostium database does not exist", "no_database", 404)
    from ostium.db.session import check_database_integrity

    try:
        check_database_integrity(source)
    except Exception as exc:
        raise BackupError(f"database integrity check failed: {exc}", "corrupt_database") from exc
    src = sqlite3.connect(source)
    dst = sqlite3.connect(destination)
    try:
        # Fold the WAL into the main database before copying so a backup taken
        # while the service is running is self-contained.
        src.execute("PRAGMA wal_checkpoint(FULL)")
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _database_requires_master_key(path: Path) -> bool:
    """Return True when the database contains fields encrypted by master.key."""

    probes = (
        ("admin_users", "totp_secret_enc"),
        ("proxy_users", "password_enc"),
        ("proxy_users", "ss_password_enc"),
        ("proxy_users", "subscription_token_enc"),
        ("profiles", "config_enc"),
        ("profiles", "subscription_url_enc"),
        ("inbounds", "params_enc"),
    )
    try:
        with sqlite3.connect(path) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            for table, column in probes:
                if table not in tables:
                    continue
                # table/column come from the fixed allowlist above, never from
                # user input.
                row = connection.execute(
                    f"SELECT 1 FROM {table} WHERE {column} IS NOT NULL AND {column} != '' LIMIT 1"  # noqa: S608
                ).fetchone()
                if row is not None:
                    return True
    except sqlite3.DatabaseError as exc:
        raise BackupError(
            f"could not inspect the backup database: {exc}", "invalid_archive"
        ) from exc
    return False


def _verify_checksums(staging: Path, manifest: dict[str, Any]) -> None:
    checksums = manifest.get("checksums")
    if checksums is None:
        # v1 backups have no checksums; the SQLite integrity check below is the
        # only portable validation available for them.
        return
    if not isinstance(checksums, dict):
        raise BackupError("backup manifest has invalid checksums", "invalid_archive")
    for name, expected in checksums.items():
        candidate = (staging / str(name)).resolve()
        try:
            candidate.relative_to(staging.resolve())
        except ValueError as exc:
            raise BackupError("backup contains an unsafe checksum path", "invalid_archive") from exc
        if not candidate.is_file():
            raise BackupError(f"backup is missing {name}", "invalid_archive")
        if not isinstance(expected, str) or _sha256_file(candidate) != expected:
            raise BackupError(f"backup file failed its checksum: {name}", "invalid_archive")


def _portable_suffix(stored: str, directory_name: str) -> str:
    """Map an old absolute path to ``<dir>/<relative...>``.

    ``..`` components are rejected instead of being carried into the restored
    database.  ``resolve_path`` also enforces the data-dir boundary, but a
    restore should fail loudly rather than silently mark every malicious
    certificate as missing.
    """

    normalized = stored.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part and part != "."]
    if ".." in parts:
        raise BackupError("backup contains a path traversal reference", "invalid_archive")
    if directory_name in parts:
        index = len(parts) - 1 - parts[::-1].index(directory_name)
        return "/".join(parts[index:])
    return f"{directory_name}/{Path(normalized).name}"


def _rewrite_portable_paths(db_path: Path, paths: Any) -> None:
    """Rewrite certificate/rule-set rows after a restore.

    A backup taken on another machine contains the old absolute paths.  New
    rows are stored relative to ``data_dir``; this also upgrades v1 backups.
    """

    try:
        with sqlite3.connect(db_path) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "certificates" in tables:
                rows = connection.execute(
                    "SELECT id, cert_path, key_path FROM certificates"
                ).fetchall()
                for certificate_id, cert_path, key_path in rows:
                    new_cert = _portable_suffix(str(cert_path), "certs")
                    new_key = _portable_suffix(str(key_path), "certs")
                    cert_file = paths.data_dir / new_cert
                    key_file = paths.data_dir / new_key
                    if cert_file.is_file() and key_file.is_file():
                        connection.execute(
                            "UPDATE certificates SET cert_path = ?, key_path = ? WHERE id = ?",
                            (new_cert, new_key, certificate_id),
                        )
                    else:
                        # Do not leave a "ready" certificate that points at
                        # files the archive did not contain; the manager would
                        # silently skip the TLS inbound and the UI would claim
                        # it is usable until an apply fails.
                        connection.execute(
                            "UPDATE certificates SET cert_path = ?, key_path = ?, "
                            "status = 'error', last_error = ? WHERE id = ?",
                            (
                                new_cert,
                                new_key,
                                "certificate files were missing from the restored backup",
                                certificate_id,
                            ),
                        )
            if "rule_sets" in tables:
                rows = connection.execute(
                    "SELECT id, path FROM rule_sets WHERE path IS NOT NULL"
                ).fetchall()
                for rule_set_id, stored in rows:
                    new_path = _portable_suffix(str(stored), "rulesets")
                    exists = (paths.data_dir / new_path).is_file()
                    connection.execute(
                        "UPDATE rule_sets SET path = ? WHERE id = ?",
                        (new_path if exists else None, rule_set_id),
                    )
            connection.commit()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"could not rewrite restored paths: {exc}", "restore_failed") from exc


def _clear_runtime_configuration(paths: Any) -> None:
    """Drop last-good/core state so the restored database is authoritative."""

    for path in (
        paths.last_good_path,
        paths.last_good_meta_path,
        paths.core_state_path,
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue
    # Enforcement names from the pre-restore database must not strip users in
    # the restored database; the next quota tick rewrites this file.
    try:
        paths.enforcement_path.unlink(missing_ok=True)
    except OSError:
        pass


def _restore_config(source: Path, settings: Settings) -> None:
    """Restore operator settings without importing another machine's paths.

    The archive was created on a host where the data, config and state
    directories (and the engine binary) may have lived elsewhere.  Copying its
    ``config.toml`` verbatim makes the next start read the old ``data_dir``:
    the database that was just restored into the current directory is ignored
    and a new empty one is created next to the old path.
    """

    import tomli_w

    try:
        with source.open("rb") as handle:
            payload = tomllib.load(handle)
    except (OSError, ValueError) as exc:
        raise BackupError(f"backup configuration is invalid: {exc}", "invalid_archive") from exc
    payload.update(
        {
            "role": settings.role.value,
            "data_dir": str(settings.data_dir),
            "config_dir": str(settings.config_dir),
            "state_dir": str(settings.state_dir),
            "core_token_file": str(settings.core_token_file),
        }
    )
    if settings.engine_path:
        payload["engine_path"] = str(settings.engine_path)
    target = settings.config_file
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            tomli_w.dump(payload, handle)
        if os.name == "posix":
            temporary.chmod(0o600)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _prepare_archive(backup_path: Path, password: str | None, workdir: Path) -> Path:
    """Return a plaintext tar path, streaming-decrypting OSTB2 when needed."""

    from ostium.util.security import BACKUP_V2_MAGIC, decrypt_stream

    with backup_path.open("rb") as probe:
        magic = probe.read(len(BACKUP_V2_MAGIC))
    if magic == BACKUP_V2_MAGIC:
        if not password:
            raise BackupError(
                "this backup is encrypted; a password is required", "password_required"
            )
        target = workdir / "backup.tar.gz"
        try:
            with backup_path.open("rb") as source_handle, target.open("wb") as output:
                decrypt_stream(source_handle, output, password)
        except CryptoError as exc:
            raise BackupError(str(exc), "invalid_password", 400) from exc
        return target
    if magic[:5] == b"OSTB1":
        if not password:
            raise BackupError(
                "this backup is encrypted; a password is required", "password_required"
            )
        raw = backup_path.read_bytes()
        try:
            plain = decrypt_blob(raw, password)
        except CryptoError as exc:
            raise BackupError(str(exc), "invalid_password", 400) from exc
        target = workdir / "backup.tar.gz"
        target.write_bytes(plain)
        return target
    return backup_path


def restore_backup(
    settings: Settings,
    backup_path: Path,
    *,
    password: str | None = None,
    include_master_key: bool = True,
) -> dict[str, Any]:
    if not backup_path.is_file():
        raise BackupError("backup file not found", "not_found", 404)
    if backup_path.stat().st_size > MAX_BACKUP_FILE_BYTES:
        raise BackupError("backup file is too large to restore", "backup_too_large", 413)
    with tempfile.TemporaryDirectory(prefix="ostium-restore-") as temp:
        staging = Path(temp)
        archive_path = _prepare_archive(backup_path, password, staging)
        try:
            with tarfile.open(archive_path, mode="r:gz") as archive:
                _safe_extract(archive, staging)
        except (tarfile.TarError, OSError) as exc:
            raise BackupError(f"backup archive is invalid: {exc}", "invalid_archive") from exc
        manifest = staging / "manifest.json"
        if not manifest.is_file():
            raise BackupError("backup is missing its manifest", "invalid_archive")
        try:
            manifest = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BackupError("backup manifest is not valid JSON", "invalid_archive") from exc
        if manifest.get("format") != "ostium-backup":
            raise BackupError("not an Ostium backup", "invalid_archive")
        if not (staging / "ostium.db").is_file():
            raise BackupError("backup does not contain a database", "invalid_archive")
        manifest_role = manifest.get("role")
        if manifest_role and manifest_role != settings.role.value:
            raise BackupError(
                f"backup belongs to the {manifest_role} role, not {settings.role.value}",
                "role_mismatch",
                409,
            )
        _verify_checksums(staging, manifest)
        from ostium.db.session import check_database_integrity, migrate_database

        try:
            check_database_integrity(staging / "ostium.db")
        except Exception as exc:
            raise BackupError(f"backup database is corrupt: {exc}", "invalid_archive") from exc
        requires_key = _database_requires_master_key(staging / "ostium.db")
        has_key = (staging / "master.key").is_file()
        if requires_key and not has_key:
            # Continuing would make every password, TOTP secret, subscription
            # token and inbound credential undecryptable, and the old code
            # silently created a new master key that could never read them.
            raise BackupError(
                "backup contains encrypted data but no master.key; restore it "
                "with the original key or the data will be unreadable",
                "missing_master_key",
                409,
            )
        if requires_key and not include_master_key:
            raise BackupError(
                "restoring encrypted data requires including the backup master.key",
                "missing_master_key",
                409,
            )
        paths = settings.paths
        paths.ensure()
        db_target = paths.db_path
        wal = paths.data_dir / "ostium.db-wal"
        shm = paths.data_dir / "ostium.db-shm"
        previous_db = staging / "previous.db"
        if db_target.is_file():
            # Snapshot through SQLite instead of copying only the main file:
            # commits still living in ostium.db-wal would otherwise be lost if
            # the post-restore migration failed and we rolled back.
            _sqlite_backup(db_target, previous_db)
        for leftover in (wal, shm):
            leftover.unlink(missing_ok=True)
        shutil.copy2(staging / "ostium.db", db_target)
        if os.name == "posix":
            db_target.chmod(0o600)
        try:
            migrate_database(db_target)
        except Exception as exc:
            if previous_db.is_file():
                shutil.copy2(previous_db, db_target)
                for leftover in (wal, shm):
                    leftover.unlink(missing_ok=True)
            else:
                db_target.unlink(missing_ok=True)
            raise BackupError(
                f"database migration failed after restore: {exc}; previous database restored",
                "migration_failed",
            ) from exc

        previous_files: dict[Path, bytes | None] = {}

        def remember(path: Path) -> None:
            if path in previous_files:
                return
            try:
                previous_files[path] = path.read_bytes() if path.is_file() else None
            except OSError:
                previous_files[path] = None

        def rollback_files() -> None:
            for path, content in previous_files.items():
                try:
                    if content is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(content)
                except OSError:
                    continue

        try:
            if include_master_key and (staging / "master.key").is_file():
                remember(paths.master_key_path)
                shutil.copy2(staging / "master.key", paths.master_key_path)
                if os.name == "posix":
                    paths.master_key_path.chmod(0o600)
            if (staging / "config.toml").is_file():
                remember(settings.config_file)
                _restore_config(staging / "config.toml", settings)
            for directory_name in BACKUP_DIRECTORIES:
                source_root = staging / directory_name
                if not source_root.is_dir():
                    continue
                destination_root = (paths.data_dir / directory_name).resolve()
                for item in source_root.rglob("*"):
                    if not item.is_file():
                        continue
                    relative = item.relative_to(source_root)
                    destination = (destination_root / relative).resolve()
                    try:
                        destination.relative_to(destination_root)
                    except ValueError as exc:
                        raise BackupError(
                            "backup contains an unsafe data path", "invalid_archive"
                        ) from exc
                    remember(destination)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, destination)
                    if os.name == "posix":
                        private = (
                            directory_name == "acme"
                            or destination.suffix == ".key"
                            or destination.name.startswith("privkey-")
                            or destination.name == "master.key"
                        )
                        destination.chmod(0o600 if private else 0o644)
            _rewrite_portable_paths(db_target, paths)
            _clear_runtime_configuration(paths)
        except Exception as exc:
            rollback_files()
            if previous_db.is_file():
                shutil.copy2(previous_db, db_target)
            for leftover in (wal, shm):
                leftover.unlink(missing_ok=True)
            if isinstance(exc, BackupError):
                raise
            raise BackupError(
                f"restore failed while replacing files: {exc}; previous state restored",
                "restore_failed",
            ) from exc
        return {
            "restored": True,
            "app_version": manifest.get("app_version"),
            "created_at": manifest.get("created_at"),
            "restart_required": True,
        }


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    total_size = 0
    for index, member in enumerate(archive.getmembers()):
        if index >= MAX_ARCHIVE_MEMBERS:
            raise BackupError("backup contains too many entries", "invalid_archive")
        total_size += max(0, int(member.size))
        if total_size > MAX_RESTORE_EXPANDED_BYTES:
            raise BackupError("backup expands beyond the restore size limit", "invalid_archive")
        raw_name = member.name
        # Validate before stripping ``./``: lstrip("./") would turn
        # ``../../manifest.json`` into an apparently safe ``manifest.json``.
        if raw_name.startswith(("/", "\\")) or (len(raw_name) > 1 and raw_name[1] == ":"):
            raise BackupError("backup contains an unsafe path", "invalid_archive")
        # Normalise Windows-created archive separators so a backup remains
        # restorable after a move between POSIX and Windows.
        name = raw_name.replace("\\", "/")
        while name.startswith("./"):
            name = name[2:]
        if member.isdir():
            continue
        if not member.isfile():
            raise BackupError("backup contains a non-regular file", "invalid_archive")
        top = name.split("/", 1)[0]
        if name not in ALLOWED_MEMBERS and top not in BACKUP_DIRECTORIES:
            raise BackupError(f"backup contains an unexpected entry: {name}", "invalid_archive")
        if ".." in Path(name).parts or Path(name).is_absolute():
            raise BackupError("backup contains an unsafe path", "invalid_archive")
        member.name = name
    archive.extractall(destination, filter="data")


def prune_automatic_backups(settings: Settings, *, keep: int = 7) -> list[str]:
    """Delete the oldest automatic plaintext backups beyond ``keep``."""

    files = sorted(
        settings.paths.backups_dir.glob(f"{AUTO_BACKUP_PREFIX}*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    removed: list[str] = []
    for path in files[keep:]:
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            continue
    return removed


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
    if backup_path.stat().st_size > MAX_BACKUP_FILE_BYTES:
        raise BackupError("backup file is too large to restore", "backup_too_large", 413)
    with backup_path.open("rb") as probe:
        magic = probe.read(5)
    encrypted = magic in {b"OSTB2", b"OSTB1"}
    if encrypted and not password:
        raise BackupError("this backup is encrypted; a password is required", "password_required")
    # Validate the complete archive, checksums, database and key pairing now,
    # while the service is still running, so a bad backup is rejected instead
    # of breaking the next startup.  OSTB2 is decrypted into a temp file rather
    # than into control-plane memory.
    from ostium.db.session import check_database_integrity

    with tempfile.TemporaryDirectory(prefix="ostium-stage-") as temp:
        staging = Path(temp)
        archive_path = _prepare_archive(backup_path, password, staging)
        try:
            with tarfile.open(archive_path, mode="r:gz") as archive:
                _safe_extract(archive, staging)
        except (tarfile.TarError, OSError) as exc:
            raise BackupError(f"backup archive is invalid: {exc}", "invalid_archive") from exc
        manifest_path = staging / "manifest.json"
        if not manifest_path.is_file():
            raise BackupError("backup is missing its manifest", "invalid_archive")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BackupError("backup manifest is not valid JSON", "invalid_archive") from exc
        if manifest.get("format") != "ostium-backup":
            raise BackupError("not an Ostium backup", "invalid_archive")
        if manifest.get("role") and manifest["role"] != settings.role.value:
            raise BackupError(
                f"backup belongs to the {manifest['role']} role, not {settings.role.value}",
                "role_mismatch",
                409,
            )
        _verify_checksums(staging, manifest)
        database = staging / "ostium.db"
        if not database.is_file():
            raise BackupError("backup does not contain a database", "invalid_archive")
        try:
            check_database_integrity(database)
        except Exception as exc:
            raise BackupError(f"backup database is corrupt: {exc}", "invalid_archive") from exc
        if _database_requires_master_key(database) and not (staging / "master.key").is_file():
            raise BackupError(
                "backup contains encrypted data but no master.key",
                "missing_master_key",
                409,
            )
    store = SecretStore.from_data_dir(settings.data_dir)
    password_token = (
        store.encrypt(password, table="settings", record_id="restore", field="password")
        if password
        else None
    )
    paths = settings.paths
    payload_path = paths.backups_dir / "restore-pending.bin"
    metadata_path = paths.backups_dir / "restore-pending.json"
    with backup_path.open("rb") as source_handle, payload_path.open("wb") as output:
        shutil.copyfileobj(source_handle, output, length=1024 * 1024)
        output.flush()
        os.fsync(output.fileno())
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
    """Apply a staged restore before the app opens the database.

    On failure the staged files are kept so the operator can retry or inspect
    the error; a successful restore consumes them.
    """

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
    except Exception as exc:
        error_path = paths.backups_dir / "restore-last-error.txt"
        error_path.write_text(f"{iso(utcnow())}: {exc}\n", encoding="utf-8")
        if os.name == "posix":
            error_path.chmod(0o600)
        raise
    payload_path.unlink(missing_ok=True)
    metadata_path.unlink(missing_ok=True)
    return result
