"""Regression tests for v0.1.2 backup portability and key safety (P0-03)."""

from __future__ import annotations

import asyncio
import io
import json
import sqlite3
import tarfile
from datetime import timedelta
from pathlib import Path

import pytest

from ostium.config import Role, Settings
from ostium.db.models import Certificate, RuleSet
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.backup import (
    BackupError,
    _portable_suffix,
    create_backup,
    restore_backup,
)
from ostium.services.crypto import SecretStore
from ostium.services.users import create_user
from ostium.util.time import utcnow


def _settings(tmp_path: Path, name: str) -> Settings:
    base = tmp_path / name
    value = Settings(
        role=Role.SERVER,
        data_dir=base / "data",
        config_dir=base / "config",
        state_dir=base / "state",
        core_token_file=base / "data" / "runtime" / "core.token",
        dev=True,
    )
    value.paths.ensure()
    return value


async def _seed(settings: Settings) -> None:
    engine = create_engine(settings.paths.db_path)
    await create_schema(engine)
    factory = create_session_factory(engine)
    store = SecretStore.from_data_dir(settings.data_dir)
    async with factory() as session:
        await create_user(session, store, name="alice")
        cert_dir = settings.paths.certs_dir / "vpn.example.com"
        cert_dir.mkdir(parents=True, exist_ok=True)
        cert_file = cert_dir / "fullchain-test.pem"
        key_file = cert_dir / "privkey-test.pem"
        cert_file.write_text("certificate", encoding="utf-8")
        key_file.write_text("private", encoding="utf-8")
        session.add(
            Certificate(
                domain="vpn.example.com",
                cert_path=str(cert_file),
                key_path=str(key_file),
                expires_at=utcnow() + timedelta(days=90),
                status="ready",
                source="manual",
                auto_renew=False,
            )
        )
        rule_file = settings.paths.rulesets_dir / "test.srs"
        rule_file.write_bytes(b"ruleset")
        session.add(
            RuleSet(
                name="test",
                url="https://example.com/test.srs",
                format="srs",
                path=str(rule_file),
            )
        )
        await session.commit()
    settings.save()
    acme = settings.data_dir / "acme"
    acme.mkdir(parents=True, exist_ok=True)
    (acme / "account.key.enc").write_text("encrypted-account-key", encoding="utf-8")
    settings.paths.last_good_path.write_text('{"stale": true}', encoding="utf-8")
    settings.paths.core_state_path.write_text('{"running": true}', encoding="utf-8")
    await engine.dispose()


def test_backup_v2_includes_rulesets_and_portable_paths(tmp_path: Path) -> None:
    async def _run() -> None:
        source = _settings(tmp_path, "source")
        await _seed(source)
        created = create_backup(source)
        with tarfile.open(created["path"]) as archive:
            names = set(archive.getnames())
            manifest = json.loads(archive.extractfile("manifest.json").read())
        assert manifest["version"] == 2
        assert "rulesets/test.srs" in names
        assert "acme/account.key.enc" in names
        assert manifest["master_key_included"] is True
        assert "ostium.db" in manifest["checksums"]

        target = _settings(tmp_path, "target")
        target.paths.last_good_path.write_text('{"old": true}', encoding="utf-8")
        target.paths.core_state_path.write_text('{"running": true}', encoding="utf-8")
        target.paths.enforcement_path.write_text('{"users": ["ghost"]}', encoding="utf-8")
        result = restore_backup(target, Path(created["path"]))
        assert result["restored"] is True
        assert (target.data_dir / "certs" / "vpn.example.com" / "fullchain-test.pem").is_file()
        assert (target.data_dir / "rulesets" / "test.srs").is_file()
        assert (target.data_dir / "acme" / "account.key.enc").is_file()
        assert (
            target.paths.master_key_path.read_bytes() == source.paths.master_key_path.read_bytes()
        )
        assert not target.paths.last_good_path.exists()
        assert not target.paths.core_state_path.exists()
        assert not target.paths.enforcement_path.exists()

        with sqlite3.connect(target.paths.db_path) as connection:
            cert = connection.execute(
                "SELECT cert_path, key_path FROM certificates WHERE domain = ?",
                ("vpn.example.com",),
            ).fetchone()
            rule = connection.execute(
                "SELECT path FROM rule_sets WHERE name = ?", ("test",)
            ).fetchone()
        assert cert == (
            "certs/vpn.example.com/fullchain-test.pem",
            "certs/vpn.example.com/privkey-test.pem",
        )
        assert rule == ("rulesets/test.srs",)

    asyncio.run(_run())


def test_backup_without_master_key_is_rejected_when_data_is_encrypted(tmp_path: Path) -> None:
    async def _run() -> None:
        source = _settings(tmp_path, "source")
        await _seed(source)
        # Creating an unrestorable backup is itself an error: a backup missing
        # the key can never recover this database.
        with pytest.raises(BackupError) as excinfo:
            create_backup(source, include_master_key=False)
        assert excinfo.value.code == "missing_master_key"

        created = create_backup(source)
        with tarfile.open(created["path"]) as archive:
            members = {
                member.name: archive.extractfile(member).read()
                for member in archive.getmembers()
                if member.isfile()
            }
        members.pop("master.key", None)
        manifest = json.loads(members["manifest.json"])
        manifest["master_key_included"] = False
        manifest.get("checksums", {}).pop("master.key", None)
        members["manifest.json"] = json.dumps(manifest).encode()
        missing_key = tmp_path / "missing-key.tar.gz"
        with tarfile.open(missing_key, "w:gz") as archive:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        target = _settings(tmp_path, "target")
        with pytest.raises(BackupError) as excinfo:
            restore_backup(target, missing_key)
        assert excinfo.value.code == "missing_master_key"
        # The target database must not be replaced by the rejected restore.
        assert not target.paths.db_path.exists()

    asyncio.run(_run())


def test_restored_paths_cannot_escape_the_data_directory(tmp_path: Path) -> None:
    from ostium.util.paths import resolve_path

    settings = _settings(tmp_path, "paths")
    with pytest.raises(BackupError, match="path traversal"):
        _portable_suffix("certs/../../etc/passwd", "certs")
    assert resolve_path(settings, "certs/../../etc/passwd") is None
    assert resolve_path(settings, "../../etc/passwd") is None


def test_modified_backup_fails_checksum_validation(tmp_path: Path) -> None:
    async def _run() -> None:
        source = _settings(tmp_path, "source")
        await _seed(source)
        created = create_backup(source)
        original = Path(created["path"])
        with tarfile.open(original) as archive:
            members = {
                member.name: archive.extractfile(member).read()
                for member in archive.getmembers()
                if member.isfile()
            }
        members["ostium.db"] = members["ostium.db"] + b"tampered"
        tampered = tmp_path / "tampered.tar.gz"
        with tarfile.open(tampered, "w:gz") as archive:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        target = _settings(tmp_path, "target")
        with pytest.raises(BackupError, match="checksum"):
            restore_backup(target, tampered)

    asyncio.run(_run())


def test_v1_manifest_still_restores(tmp_path: Path) -> None:
    async def _run() -> None:
        source = _settings(tmp_path, "source")
        await _seed(source)
        created = create_backup(source)
        legacy = tmp_path / "legacy.tar.gz"
        with tarfile.open(created["path"]) as archive:
            members = {
                member.name: archive.extractfile(member).read()
                for member in archive.getmembers()
                if member.isfile()
            }
        manifest = json.loads(members["manifest.json"])
        manifest["version"] = 1
        manifest.pop("checksums", None)
        members["manifest.json"] = json.dumps(manifest).encode()
        with tarfile.open(legacy, "w:gz") as archive:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        target = _settings(tmp_path, "target")
        assert restore_backup(target, legacy)["restored"] is True

    asyncio.run(_run())
