"""Focused regression coverage for review-round hardening paths."""

from __future__ import annotations

import asyncio
import io
import json
import tarfile
from pathlib import Path

import pytest

from ostium.config import Role, Settings
from ostium.db.models import Alert
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services import audit as audit_service
from ostium.services import backup as backup_service
from ostium.services.enforcement import (
    read_enforcement,
    strip_disabled_users,
    write_enforcement,
)
from ostium.services.events import EventBus
from ostium.services.settings import set_setting
from ostium.util.paths import resolve_path, store_path
from ostium.util.redact import redact, redact_mapping


def _settings(tmp_path: Path, name: str = "data") -> Settings:
    value = Settings(
        role=Role.SERVER,
        data_dir=tmp_path / name,
        config_dir=tmp_path / f"{name}-config",
        state_dir=tmp_path / f"{name}-state",
        core_token_file=tmp_path / name / "runtime" / "core.token",
        dev=True,
    )
    value.paths.ensure()
    return value


async def _schema(settings: Settings):
    engine = create_engine(settings.paths.db_path)
    await create_schema(engine)
    return engine, create_session_factory(engine)


def test_enforcement_rejects_malformed_policy_and_strips_edges(tmp_path: Path) -> None:
    path = tmp_path / "enforcement.json"
    assert read_enforcement(path) == set()
    path.write_text("{bad", encoding="utf-8")
    assert read_enforcement(path) == set()
    path.write_text(json.dumps({"version": 99, "users": ["a"]}), encoding="utf-8")
    assert read_enforcement(path) == set()
    path.write_text(json.dumps({"version": 1, "users": "not-a-list"}), encoding="utf-8")
    assert read_enforcement(path) == set()
    write_enforcement(path, ["bob", "", "alice", "alice"])
    assert read_enforcement(path) == {"alice", "bob"}

    config = {
        "inbounds": [
            "not-a-dict",
            {"tag": "no-users"},
            {"tag": "bad-users", "users": "nope"},
            {"tag": "users", "users": [{"name": "alice"}, {"name": "carol"}, "static"]},
        ]
    }
    assert strip_disabled_users(config, set()) == (config, False)
    assert strip_disabled_users({"inbounds": "no"}, {"alice"}) == ({"inbounds": "no"}, False)
    clone, changed = strip_disabled_users(config, {"alice"})
    assert changed is True
    assert clone["inbounds"][3]["users"] == [{"name": "carol"}, "static"]
    _, unchanged = strip_disabled_users(config, {"nobody"})
    assert unchanged is False


def test_paths_and_redaction_edge_branches(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    inside = settings.data_dir / "certs" / "a.pem"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_text("x", encoding="utf-8")
    assert store_path(settings, inside) == "certs/a.pem"
    external = tmp_path / "external.pem"
    external.write_text("x", encoding="utf-8")
    assert store_path(settings, external) == external.resolve().as_posix()
    assert resolve_path(settings, external) == external
    assert resolve_path(settings, "certs/a.pem") == inside.resolve()
    assert resolve_path(settings, "certs/../../etc/passwd") is None
    assert resolve_path(settings, None) is None

    nested = redact_mapping(
        {
            "plain": "bearer abc",
            "webhook_secret": "hide-me",
            "tuple": ({"ss_password": "hide"}, ["token=abc"]),
            "number": 3,
            "list": [{"private_key": "hide"}, ("x", 1)],
        }
    )
    assert nested["webhook_secret"] == "[REDACTED]"
    assert "hide" not in json.dumps(nested)
    assert nested["number"] == 3
    assert redact("https://x/sub/abcdefghijk") == "https://x/sub/[REDACTED]"
    assert redact("") == ""


def test_audit_secret_resolution_and_dedupe(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine, factory = await _schema(settings)
        bus = EventBus()
        async with factory() as session:
            await set_setting(session, "webhook_secret", "plain-secret")
            await session.commit()
            assert await audit_service._webhook_secret(session) == "plain-secret"
            await set_setting(session, "webhook_secret", "v1.not-decryptable")
            await session.commit()
            audit_service.set_webhook_secret_decrypter(None)
            with pytest.raises(ValueError, match="no decrypter"):
                await audit_service._webhook_secret(session)
            audit_service.set_webhook_secret_decrypter(lambda value: "decrypted")
            assert await audit_service._webhook_secret(session) == "decrypted"

            first = await audit_service.create_alert(
                session, bus, level="warning", code="quota", message="first", dedupe_key="u1"
            )
            await session.commit()
            second = await audit_service.create_alert(
                session, bus, level="critical", code="quota", message="second", dedupe_key="u1"
            )
            await session.commit()
            assert first.id == second.id
            assert second.level == "critical"
            assert second.message == "second"

        await engine.dispose()

    asyncio.run(_run())


def test_backup_edge_paths_and_restore_validation(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine, _factory = await _schema(settings)
        await engine.dispose()

        with pytest.raises(backup_service.BackupError) as excinfo:
            backup_service.create_backup(settings, target=tmp_path)
        assert excinfo.value.code == "invalid_target"

        target = tmp_path / "one.tar.gz"
        target.write_bytes(b"exists")
        with pytest.raises(backup_service.BackupError) as excinfo:
            backup_service.create_backup(settings, target=target)
        assert excinfo.value.code == "exists"

        missing = _settings(tmp_path, "missing")
        with pytest.raises(backup_service.BackupError) as excinfo:
            backup_service.create_backup(missing)
        assert excinfo.value.code == "no_database"

        created = backup_service.create_backup(settings)
        with pytest.raises(backup_service.BackupError) as excinfo:
            backup_service.restore_backup(settings, Path(str(created["path"]) + ".missing"))
        assert excinfo.value.code == "not_found"

        # Direct helper validation branches.
        staging = tmp_path / "staging"
        staging.mkdir()
        with pytest.raises(backup_service.BackupError):
            backup_service._verify_checksums(staging, {"checksums": {"../x": "0"}})
        with pytest.raises(backup_service.BackupError):
            backup_service._verify_checksums(staging, {"checksums": {"missing": "0"}})
        (staging / "file").write_text("data", encoding="utf-8")
        with pytest.raises(backup_service.BackupError):
            backup_service._verify_checksums(staging, {"checksums": {"file": "0"}})
        assert backup_service._portable_suffix("/x/certs/a.pem", "certs") == "certs/a.pem"
        assert backup_service._portable_suffix("/x/other/a.pem", "certs") == "certs/a.pem"

        unsafe = io.BytesIO()
        with tarfile.open(fileobj=unsafe, mode="w:gz") as archive:
            data = b"x"
            info = tarfile.TarInfo("../evil")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        unsafe.seek(0)
        with (
            tarfile.open(fileobj=unsafe, mode="r:gz") as archive,
            pytest.raises(backup_service.BackupError),
        ):
            backup_service._safe_extract(archive, staging)

        # A role-mismatched archive is rejected before touching the database.
        client = _settings(tmp_path, "client")
        client.role = Role.CLIENT
        with pytest.raises(backup_service.BackupError) as excinfo:
            backup_service.restore_backup(client, Path(created["path"]))
        assert excinfo.value.code == "role_mismatch"

        # A wrong password is a controlled error, not a crypto traceback.
        encrypted = backup_service.create_backup(settings, password="long-passphrase")
        with pytest.raises(backup_service.BackupError) as excinfo:
            backup_service.restore_backup(
                settings, Path(encrypted["path"]), password="wrong-password"
            )
        assert excinfo.value.code == "invalid_password"

    asyncio.run(_run())


def test_audit_webhook_uses_pinned_post(monkeypatch) -> None:
    calls: list[tuple[str, bytes]] = []

    async def fake_post(url: str, *, content: bytes, headers=None, timeout=10.0):
        calls.append((url, content))
        return 204

    monkeypatch.setattr(audit_service, "post_limited", fake_post, raising=False)
    monkeypatch.setattr("ostium.services.netguard.post_limited", fake_post)
    assert asyncio.run(
        audit_service.send_webhook("https://hooks.example.com/x", {"a": 1}, "secret")
    )
    assert calls and calls[0][0].startswith("https://")


def test_rule_set_payload_and_certificate_generation_cleanup(tmp_path: Path) -> None:
    from ostium.services.certificates import remove_certificate_files
    from ostium.services.rules import RuleValidationError, _validate_rule_set_payload

    assert _validate_rule_set_payload(b'{"rules": []}', "source") is None
    with pytest.raises(RuleValidationError, match="JSON"):
        _validate_rule_set_payload(b"{bad", "source")
    with pytest.raises(RuleValidationError, match="rules array"):
        _validate_rule_set_payload(b"{}", "source")
    with pytest.raises(RuleValidationError, match="unsupported"):
        _validate_rule_set_payload(b"SRSx", "mystery")

    directory = tmp_path / "certs" / "example.com"
    directory.mkdir(parents=True)
    (directory / ".ostium-domain").write_text("example.com", encoding="utf-8")
    first = directory / "fullchain-a.pem"
    old = directory / "fullchain-b.pem"
    first.write_text("x", encoding="utf-8")
    old.write_text("x", encoding="utf-8")
    remove_certificate_files([first], domain="example.com")
    assert not first.exists()
    assert not old.exists()

    other = tmp_path / "certs" / "other.example"
    other.mkdir(parents=True)
    (other / ".ostium-domain").write_text("other.example", encoding="utf-8")
    keep = other / "fullchain-c.pem"
    keep.write_text("x", encoding="utf-8")
    remove_certificate_files([other / "fullchain-missing.pem"], domain="example.com")
    assert keep.exists()


def test_database_key_probe_and_session_helpers(tmp_path: Path) -> None:
    from ostium.db.session import database_requires_master_key, tighten_permissions

    async def _run() -> None:
        settings = _settings(tmp_path)
        engine, factory = await _schema(settings)
        assert database_requires_master_key(settings.paths.db_path) is False
        async with factory() as session:
            session.add(Alert(level="warning", code="x", message="x"))
            await session.commit()
        assert database_requires_master_key(settings.paths.db_path) is False
        await engine.dispose()

    asyncio.run(_run())
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"not sqlite")
    assert database_requires_master_key(corrupt) is True
    tighten_permissions(corrupt)
