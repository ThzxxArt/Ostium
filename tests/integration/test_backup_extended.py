from __future__ import annotations

import asyncio
import io
import json
import tarfile
from pathlib import Path

import pytest

from ostium.config import Role, Settings
from ostium.db.session import create_engine, create_schema
from ostium.services import backup as backup_service
from ostium.services.backup import (
    BackupError,
    _safe_extract,
    _sqlite_backup,
    apply_pending_restore,
    backup_record,
    create_backup,
    restore_backup,
    stage_restore,
)


def _settings(tmp_path: Path, name: str = "node") -> Settings:
    data = tmp_path / name
    value = Settings(
        role=Role.SERVER,
        data_dir=data,
        config_dir=tmp_path / f"{name}-config",
        state_dir=tmp_path / f"{name}-state",
        core_token_file=data / "runtime" / "core.token",
        dev=True,
    )
    value.paths.ensure()
    value.save()
    return value


def _seed(settings: Settings) -> None:
    async def _run() -> None:
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        await engine.dispose()

    asyncio.run(_run())


def test_backup_requires_database(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "missing-db")
    settings.paths.db_path.unlink(missing_ok=True)
    with pytest.raises(BackupError) as excinfo:
        create_backup(settings)
    assert excinfo.value.code == "no_database"
    with pytest.raises(BackupError):
        _sqlite_backup(settings.paths.db_path, tmp_path / "copy.db")


def test_backup_plain_and_metadata(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "plain")
    _seed(settings)
    (settings.paths.certs_dir / "vpn.example.com").mkdir()
    (settings.paths.certs_dir / "vpn.example.com" / "fullchain.pem").write_text("cert")
    settings.paths.config_file.write_text("role = 'server'")

    result = create_backup(settings, include_master_key=False)
    path = Path(result["path"])
    assert result["encrypted"] is False
    assert path.name.endswith(".tar.gz")
    with tarfile.open(path) as archive:
        names = set(archive.getnames())
    assert "ostium.db" in names
    assert "manifest.json" in names
    assert "config.toml" in names
    assert "certs/vpn.example.com/fullchain.pem" in names
    assert "master.key" not in names
    record = backup_record(result)
    assert record["sha256"] == result["sha256"]
    assert set(record) == {"filename", "size", "sha256", "encrypted", "created_at"}


def test_backup_name_collision(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, "collision")
    _seed(settings)

    from datetime import UTC, datetime

    frozen = datetime(2024, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(backup_service, "utcnow", lambda: frozen)
    first = create_backup(settings)
    assert first["filename"] == "ostium-backup-20240101-000000.tar.gz"
    with pytest.raises(BackupError) as excinfo:
        create_backup(settings)
    assert excinfo.value.code == "exists"


def test_restore_validation_errors(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "restore")
    _seed(settings)

    with pytest.raises(BackupError) as missing:
        restore_backup(settings, tmp_path / "missing.tar.gz")
    assert missing.value.status_code == 404

    bad = tmp_path / "bad.tar.gz"
    bad.write_bytes(b"not an archive")
    with pytest.raises(BackupError) as invalid:
        restore_backup(settings, bad)
    assert invalid.value.code == "invalid_archive"

    encrypted = create_backup(settings, password="backup-password")
    with pytest.raises(BackupError) as required:
        restore_backup(settings, Path(encrypted["path"]))
    assert required.value.code == "password_required"
    with pytest.raises(BackupError) as wrong:
        restore_backup(settings, Path(encrypted["path"]), password="wrong-password")
    assert wrong.value.code == "invalid_password"


def _tar(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def test_restore_archive_structure_errors(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "structure")
    _seed(settings)
    payload = tmp_path / "payload.tar.gz"

    _tar(payload, {"ostium.db": b"db"})
    with pytest.raises(BackupError, match="manifest"):
        restore_backup(settings, payload)

    _tar(
        payload,
        {
            "ostium.db": b"db",
            "manifest.json": json.dumps({"format": "other"}).encode(),
        },
    )
    with pytest.raises(BackupError, match="not an Ostium backup"):
        restore_backup(settings, payload)

    _tar(payload, {"manifest.json": json.dumps({"format": "ostium-backup"}).encode()})
    with pytest.raises(BackupError, match="does not contain a database"):
        restore_backup(settings, payload)


@pytest.mark.parametrize(
    "member",
    ["../evil", "/absolute", "unexpected.txt", "certs/ok/../../evil", "certs/../../evil"],
)
def test_safe_extract_rejects_unsafe_members(member: str, tmp_path: Path) -> None:
    payload = tmp_path / "unsafe.tar.gz"
    with tarfile.open(payload, "w:gz") as archive:
        info = tarfile.TarInfo(member)
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    with tarfile.open(payload) as archive, pytest.raises(BackupError):
        _safe_extract(archive, tmp_path / "out")


def test_safe_extract_rejects_non_regular(tmp_path: Path) -> None:
    payload = tmp_path / "link.tar.gz"
    with tarfile.open(payload, "w:gz") as archive:
        info = tarfile.TarInfo("certs/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        archive.addfile(info)
    with tarfile.open(payload) as archive, pytest.raises(BackupError, match="non-regular"):
        _safe_extract(archive, tmp_path / "out")


def test_restore_plain_copies_files(tmp_path: Path) -> None:
    source = _settings(tmp_path, "source-plain")
    _seed(source)
    (source.paths.certs_dir / "example.com").mkdir()
    (source.paths.certs_dir / "example.com" / "cert.pem").write_text("cert")
    result = create_backup(source)

    target = _settings(tmp_path, "target-plain")
    target.paths.certs_dir.mkdir(parents=True, exist_ok=True)
    (target.paths.certs_dir / "old.pem").write_text("old")
    restored = restore_backup(target, Path(result["path"]))
    assert restored["restored"] is True
    assert target.paths.db_path.is_file()
    assert (target.paths.certs_dir / "example.com" / "cert.pem").read_text() == "cert"
    assert (target.paths.certs_dir / "old.pem").exists()
    assert target.paths.config_file.is_file()


def test_restore_without_master_key_keeps_existing(tmp_path: Path) -> None:
    source = _settings(tmp_path, "source-nokey")
    _seed(source)
    result = create_backup(source, include_master_key=False)
    target = _settings(tmp_path, "target-nokey")
    from ostium.services.crypto import SecretStore

    SecretStore.from_data_dir(target.data_dir)
    assert target.paths.master_key_path.is_file()
    original = target.paths.master_key_path.read_bytes()
    restore_backup(target, Path(result["path"]), include_master_key=False)
    assert target.paths.master_key_path.read_bytes() == original


def test_stage_and_apply_pending_restore(tmp_path: Path) -> None:
    source = _settings(tmp_path, "source-stage")
    _seed(source)
    created = create_backup(source, password="backup-password")

    target = _settings(tmp_path, "target-stage")
    staged = stage_restore(target, Path(created["path"]), password="backup-password")
    assert staged == {
        "staged": True,
        "encrypted": True,
        "filename": Path(created["path"]).name,
    }
    assert (target.paths.backups_dir / "restore-pending.bin").is_file()
    applied = apply_pending_restore(target)
    assert applied is not None
    assert applied["filename"] == Path(created["path"]).name
    assert applied["restored"] is True
    assert not (target.paths.backups_dir / "restore-pending.bin").exists()
    assert not (target.paths.backups_dir / "restore-pending.json").exists()
    assert apply_pending_restore(target) is None


def test_stage_restore_password_validation(tmp_path: Path) -> None:
    source = _settings(tmp_path, "source-stage-bad")
    _seed(source)
    created = create_backup(source, password="backup-password")
    target = _settings(tmp_path, "target-stage-bad")

    with pytest.raises(BackupError) as missing:
        stage_restore(target, Path(created["path"]))
    assert missing.value.code == "password_required"
    with pytest.raises(BackupError) as wrong:
        stage_restore(target, Path(created["path"]), password="wrong-password")
    assert wrong.value.code == "invalid_password"
    with pytest.raises(BackupError) as not_found:
        stage_restore(target, tmp_path / "missing.ostb")
    assert not_found.value.status_code == 404


def test_apply_pending_restore_invalid_metadata(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "pending-invalid")
    payload = settings.paths.backups_dir / "restore-pending.bin"
    metadata = settings.paths.backups_dir / "restore-pending.json"
    payload.write_bytes(b"x")
    metadata.write_text("{invalid")
    with pytest.raises(json.JSONDecodeError):
        apply_pending_restore(settings)
    assert not payload.exists()
    assert not metadata.exists()
