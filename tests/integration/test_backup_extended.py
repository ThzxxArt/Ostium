from __future__ import annotations

import asyncio
import io
import json
import sqlite3
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
    assert first["filename"] == "ostium-backup-20240101-000000-000000.tar.gz"
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
    [
        "../evil",
        "./../evil",
        "/absolute",
        "unexpected.txt",
        "certs/ok/../../evil",
        "certs/../../evil",
        "..\\evil",
    ],
)
def test_safe_extract_rejects_unsafe_members(member: str, tmp_path: Path) -> None:
    payload = tmp_path / "unsafe.tar.gz"
    with tarfile.open(payload, "w:gz") as archive:
        info = tarfile.TarInfo(member)
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    with tarfile.open(payload) as archive, pytest.raises(BackupError):
        _safe_extract(archive, tmp_path / "out")


def test_safe_extract_normalises_windows_separators(tmp_path: Path) -> None:
    payload = tmp_path / "windows.tar.gz"
    _tar(
        payload,
        {
            "manifest.json": b"{}",
            "certs\\vpn.example.com\\fullchain.pem": b"cert",
        },
    )
    destination = tmp_path / "out"
    with tarfile.open(payload) as archive:
        _safe_extract(archive, destination)
    assert (destination / "certs" / "vpn.example.com" / "fullchain.pem").read_bytes() == b"cert"

    drive = tmp_path / "drive.tar.gz"
    _tar(drive, {"C:evil": b"x"})
    with tarfile.open(drive) as archive, pytest.raises(BackupError, match="unsafe path"):
        _safe_extract(archive, tmp_path / "out2")


def test_safe_extract_rejects_non_regular(tmp_path: Path) -> None:
    payload = tmp_path / "link.tar.gz"
    with tarfile.open(payload, "w:gz") as archive:
        info = tarfile.TarInfo("certs/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        archive.addfile(info)
    with tarfile.open(payload) as archive, pytest.raises(BackupError, match="non-regular"):
        _safe_extract(archive, tmp_path / "out")


def _backup_with_newer_schema(source: Settings, tmp_path: Path) -> Path:
    created = create_backup(source)
    with tarfile.open(created["path"]) as archive:
        members = {
            member.name: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile()
        }
    database = tmp_path / "newer.db"
    database.write_bytes(members["ostium.db"])
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE alembic_version SET version_num='999999999999'")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(FULL)")
    members["ostium.db"] = database.read_bytes()
    output = tmp_path / "newer.tar.gz"
    with tarfile.open(output, "w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return output


def test_restore_migration_failure_keeps_previous_database(tmp_path: Path) -> None:
    source = _settings(tmp_path, "source-newer")
    _seed(source)
    payload = _backup_with_newer_schema(source, tmp_path)

    target = _settings(tmp_path, "target-newer")
    _seed(target)
    with sqlite3.connect(target.paths.db_path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO settings(key,value_json,updated_at) VALUES (?,?,?)",
            ("marker", '"kept"', "2026-01-01T00:00:00+00:00"),
        )
        connection.commit()

    with pytest.raises(BackupError) as excinfo:
        restore_backup(target, payload)
    assert excinfo.value.code == "migration_failed"
    with sqlite3.connect(target.paths.db_path) as connection:
        row = connection.execute("SELECT value_json FROM settings WHERE key='marker'").fetchone()
    assert row == ('"kept"',)


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
    assert payload.exists()
    assert metadata.exists()
    assert (settings.paths.backups_dir / "restore-last-error.txt").is_file()


def test_restore_rejects_role_mismatch_and_bad_archive(tmp_path: Path) -> None:
    server = _settings(tmp_path, "server")
    _seed(server)
    created = create_backup(server)
    client = Settings(
        role=Role.CLIENT,
        data_dir=tmp_path / "client",
        config_dir=tmp_path / "client-config",
        state_dir=tmp_path / "client-state",
        core_token_file=tmp_path / "client" / "runtime" / "core.token",
        dev=True,
    )
    client.paths.ensure()
    _seed(client)
    with pytest.raises(BackupError) as mismatch:
        restore_backup(client, Path(created["path"]))
    assert mismatch.value.code == "role_mismatch"
    assert mismatch.value.status_code == 409

    garbage = tmp_path / "garbage.tar.gz"
    garbage.write_bytes(b"not an archive")
    with pytest.raises(BackupError) as invalid:
        restore_backup(server, garbage)
    assert invalid.value.code == "invalid_archive"

    with pytest.raises(BackupError) as staged_invalid:
        stage_restore(server, garbage)
    assert staged_invalid.value.code == "invalid_archive"


def test_automatic_backup_retention(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "retention")
    _seed(settings)
    for _index in range(9):
        create_backup(settings, automatic=True)
    removed = backup_service.prune_automatic_backups(settings, keep=7)
    assert len(removed) == 2
    remaining = list(settings.paths.backups_dir.glob("ostium-auto-backup-*"))
    assert len(remaining) == 7


def test_backup_rejects_directory_target_and_corrupt_database(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "target")
    _seed(settings)
    with pytest.raises(BackupError) as target:
        create_backup(settings, target=tmp_path)
    assert target.value.code == "invalid_target"

    with sqlite3.connect(settings.paths.db_path) as connection:
        connection.execute("DROP TABLE admin_users")
        connection.execute("CREATE TABLE admin_users (broken TEXT)")
        connection.commit()
    settings.paths.db_path.write_bytes(b"garbage")
    with pytest.raises(BackupError) as corrupt:
        create_backup(settings)
    assert corrupt.value.code in {"corrupt_database", "no_database"}


def test_safe_extract_rejects_unsafe_entries(tmp_path: Path) -> None:
    absolute = tmp_path / "absolute.tar.gz"
    with tarfile.open(absolute, "w:gz") as archive:
        info = tarfile.TarInfo("/etc/passwd")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    with tarfile.open(absolute) as archive, pytest.raises(BackupError):
        _safe_extract(archive, tmp_path / "out")

    non_regular = tmp_path / "link.tar.gz"
    with tarfile.open(non_regular, "w:gz") as archive:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        archive.addfile(info)
    with tarfile.open(non_regular) as archive, pytest.raises(BackupError):
        _safe_extract(archive, tmp_path / "out")


def test_apply_pending_restore_success_consumes_files(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "pending-ok")
    _seed(settings)
    created = create_backup(settings)
    source = Path(created["path"])
    payload = settings.paths.backups_dir / "restore-pending.bin"
    metadata = settings.paths.backups_dir / "restore-pending.json"
    payload.write_bytes(source.read_bytes())
    metadata.write_text(json.dumps({"filename": source.name, "encrypted": False}))
    result = apply_pending_restore(settings)
    assert result is not None and result["restored"] is True
    assert not payload.exists()
    assert not metadata.exists()


def test_stage_restore_rejects_missing_or_foreign_manifest(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "stage-manifest")
    _seed(settings)

    no_manifest = tmp_path / "no-manifest.tar.gz"
    with tarfile.open(no_manifest, "w:gz") as archive:
        data = b"database"
        info = tarfile.TarInfo("ostium.db")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    with pytest.raises(BackupError) as missing:
        stage_restore(settings, no_manifest)
    assert missing.value.code == "invalid_archive"

    foreign = tmp_path / "foreign.tar.gz"
    with tarfile.open(foreign, "w:gz") as archive:
        data = json.dumps({"format": "something-else"}).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    with pytest.raises(BackupError) as bad_format:
        stage_restore(settings, foreign)
    assert bad_format.value.code == "invalid_archive"
