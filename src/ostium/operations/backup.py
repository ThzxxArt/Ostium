"""Encrypted, portable backups.

Format ``OSTB1``:

    magic (5) | salt (16) | nonce (12) | AES-256-GCM(tar.gz)

The password is stretched with scrypt. The archive contains a JSON database
dump, certificates, the applied data-plane config and the field-encryption key
needed to decrypt credentials after a restore.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import tempfile
from datetime import UTC
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from ostium import paths
from ostium.version import __version__

from .models import Backup

MAGIC = b"OSTB1"
SALT_BYTES = 16
NONCE_BYTES = 12


class BackupError(RuntimeError):
    pass


def _derive(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(password.encode("utf-8"))


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes, mode: int = 0o600) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    info.mtime = int(timezone.now().timestamp())
    tar.addfile(info, io.BytesIO(data))


def _add_path(tar: tarfile.TarFile, path: Path, arcname: str) -> None:
    if not path.exists():
        return
    if path.is_dir():
        for child in sorted(path.rglob("*")):
            if child.is_file():
                _add_path(tar, child, f"{arcname}/{child.relative_to(path)}")
        return
    info = tarfile.TarInfo(arcname)
    info.size = path.stat().st_size
    info.mode = 0o600
    info.mtime = int(path.stat().st_mtime)
    with path.open("rb") as handle:
        tar.addfile(info, handle)


def _database_dump() -> bytes:
    buffer = io.StringIO()
    call_command(
        "dumpdata",
        format="json",
        indent=2,
        stdout=buffer,
        exclude=[
            "contenttypes",
            "auth.permission",
            "sessions",
            "admin",
            "django_q",
        ],
    )
    return buffer.getvalue().encode("utf-8")


def create_backup(*, password: str, note: str = "", actor=None) -> Backup:
    if len(password) < 12:
        raise BackupError("Backup password must be at least 12 characters.")
    if not password:
        raise BackupError("Backup password is required.")
    paths.ensure()
    now = timezone.now()
    timestamp = now.astimezone(UTC).strftime("%Y%m%d-%H%M%S")
    filename = f"ostium-backup-{timestamp}.ostb"
    target = paths.backups_dir() / filename

    with tempfile.TemporaryDirectory(prefix="ostium-backup-") as tempdir:
        temp = Path(tempdir)
        db_bytes = _database_dump()
        (temp / "database.json").write_bytes(db_bytes)
        manifest = {
            "format": 1,
            "product": "ostium-server",
            "version": __version__,
            "created_at": now.isoformat(),
            "field_key": settings.OSTIUM_FIELD_KEY,
            "database_sha256": hashlib.sha256(db_bytes).hexdigest(),
        }
        (temp / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        raw = temp / "payload.tar.gz"
        with tarfile.open(raw, "w:gz") as tar:
            tar.add(temp / "manifest.json", arcname="manifest.json")
            tar.add(temp / "database.json", arcname="database.json")
            _add_path(tar, paths.certs_dir(), "certs")
            _add_path(tar, paths.config_path(), "runtime/config.json")
        payload = raw.read_bytes()

    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(_derive(password, salt)).encrypt(nonce, payload, MAGIC)
    blob = MAGIC + salt + nonce + ciphertext
    target.write_bytes(blob)
    paths.secure_file(target)
    digest = hashlib.sha256(blob).hexdigest()

    backup = Backup.objects.create(
        filename=filename,
        size=len(blob),
        sha256=digest,
        encrypted=True,
        note=note,
        created_by=actor if getattr(actor, "pk", None) else None,
    )
    return backup


def decrypt_archive(data: bytes, password: str) -> bytes:
    if not data.startswith(MAGIC):
        raise BackupError("Not an Ostium backup file.")
    offset = len(MAGIC)
    salt = data[offset : offset + SALT_BYTES]
    nonce = data[offset + SALT_BYTES : offset + SALT_BYTES + NONCE_BYTES]
    ciphertext = data[offset + SALT_BYTES + NONCE_BYTES :]
    try:
        return AESGCM(_derive(password, salt)).decrypt(nonce, ciphertext, MAGIC)
    except Exception as exc:
        raise BackupError("Could not decrypt the backup. Check the password and file integrity.") from exc


def delete_backup(backup: Backup, *, actor=None) -> None:
    """Delete a backup record and its archive file."""

    filename = backup.filename
    (paths.backups_dir() / filename).unlink(missing_ok=True)
    backup.delete()
    from .services import record_audit

    record_audit(action="backup.deleted", actor=actor, target=filename)


def restore_backup(backup: Backup, *, password: str, actor=None) -> None:
    source = paths.backups_dir() / backup.filename
    restore_file(source, password=password, actor=actor)


def _reencrypt_with_field_key(backup_key: str) -> bool:
    """Re-encrypt restored rows with the host's current field key.

    Backups are portable: the archive contains the field key that was active
    when it was created. Restoring on a host with a different key must not
    leave credentials undecryptable.
    """

    import base64

    from django.db import transaction

    from ostium.accounts.crypto import decrypt_json, decrypt_text, encrypt_json, encrypt_text
    from ostium.proxy.models import Inbound, ProxyUser

    if backup_key == settings.OSTIUM_FIELD_KEY:
        return False
    try:
        if len(base64.b64decode(backup_key)) != 32:
            raise ValueError
    except Exception as exc:
        raise BackupError("Backup manifest contains an invalid field key.") from exc

    current_key = settings.OSTIUM_FIELD_KEY
    try:
        settings.OSTIUM_FIELD_KEY = backup_key
        users = list(ProxyUser.objects.all())
        inbounds = list(Inbound.objects.all())
        plain_users = [
            (
                user.pk,
                decrypt_text(user, "password_enc", user.password_enc),
                decrypt_text(user, "ss_password_enc", user.ss_password_enc),
                decrypt_text(user, "subscription_token_enc", user.subscription_token_enc),
            )
            for user in users
        ]
        plain_inbounds = [(inbound.pk, decrypt_json(inbound, "params_enc", inbound.params_enc)) for inbound in inbounds]
    except Exception as exc:
        raise BackupError(
            "The backup was encrypted with a different field key and its credentials could not be read."
        ) from exc
    finally:
        settings.OSTIUM_FIELD_KEY = current_key

    with transaction.atomic():
        for pk, password, ss_password, token in plain_users:
            user = ProxyUser(pk=pk)
            ProxyUser.objects.filter(pk=pk).update(
                password_enc=encrypt_text(user, "password_enc", password),
                ss_password_enc=encrypt_text(user, "ss_password_enc", ss_password),
                subscription_token_enc=encrypt_text(user, "subscription_token_enc", token),
            )
        for pk, params in plain_inbounds:
            inbound = Inbound(pk=pk)
            Inbound.objects.filter(pk=pk).update(params_enc=encrypt_json(inbound, "params_enc", params))
    return True


def restore_file(source: Path, *, password: str, actor=None) -> None:
    if not source.is_file():
        raise BackupError("Backup file is missing.")
    payload = decrypt_archive(source.read_bytes(), password)
    with tempfile.TemporaryDirectory(prefix="ostium-restore-") as tempdir:
        staging = Path(tempdir)
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
            for member in tar.getmembers():
                member_path = Path(member.name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise BackupError("Backup contains an unsafe path.")
            # Members are validated above (no absolute paths, no traversal);
            # Python's data filter is a second layer of defence.
            tar.extractall(staging, filter="data")  # nosec B202

        manifest_path = staging / "manifest.json"
        if not manifest_path.is_file():
            raise BackupError("Backup manifest is missing.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("product") != "ostium-server" or manifest.get("format") != 1:
            raise BackupError("Unsupported backup format.")
        database_path = staging / "database.json"
        if not database_path.is_file():
            raise BackupError("Database dump is missing from the backup.")
        digest = hashlib.sha256(database_path.read_bytes()).hexdigest()
        if digest != manifest.get("database_sha256"):
            raise BackupError("Database checksum does not match the manifest.")

        call_command("flush", interactive=False, verbosity=0)
        call_command("loaddata", str(database_path), verbosity=0)
        call_command("migrate", interactive=False, verbosity=0)
        if _reencrypt_with_field_key(str(manifest.get("field_key") or "")):
            from .services import record_audit

            record_audit(action="backup.field_key_reencrypted", actor=actor, target=source.name)

        source_certs = staging / "certs"
        if source_certs.is_dir():
            for folder in source_certs.iterdir():
                if not folder.is_dir():
                    continue
                target = paths.certs_dir() / folder.name
                target.mkdir(parents=True, exist_ok=True)
                try:
                    target.chmod(0o700)
                except OSError:
                    pass
                for item in folder.iterdir():
                    if item.is_file():
                        destination = target / item.name
                        destination.write_bytes(item.read_bytes())
                        paths.secure_file(destination)

        config_file = staging / "runtime" / "config.json"
        if config_file.is_file():
            paths.runtime_dir().mkdir(parents=True, exist_ok=True)
            target_config = paths.config_path()
            target_config.write_bytes(config_file.read_bytes())
            paths.secure_file(target_config)

    Backup.objects.filter(filename=source.name).update(restored_at=timezone.now())
    from .models import RuntimeState

    RuntimeState.mark_desired()
