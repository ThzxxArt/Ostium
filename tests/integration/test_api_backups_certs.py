from __future__ import annotations

import datetime as dt
import sqlite3
import time
from pathlib import Path
from typing import ClassVar

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from ostium.api.routes_backups import file_digest
from ostium.config import Settings
from ostium.engine.manager import EngineError


def _headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


def _bundle(domain: str) -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=90))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(domain)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return (
        certificate.public_bytes(serialization.Encoding.PEM).decode(),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )


def _wait_job(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()["job"]
        if job["status"] not in {"queued", "running"}:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {job}")


def _sql(settings: Settings, statement: str, params: tuple[object, ...] = ()) -> None:
    with sqlite3.connect(settings.paths.db_path) as connection:
        connection.execute(statement, params)
        connection.commit()


def test_backup_create_list_restore_delete(
    api_client: TestClient, session_token: str, settings: Settings
) -> None:
    headers = _headers(session_token)
    rejected = api_client.post("/api/v1/backups", json={}, headers=headers)
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "plaintext_backup_requires_acknowledgement"
    created = api_client.post(
        "/api/v1/backups", json={"acknowledge_plaintext": True}, headers=headers
    )
    assert created.status_code == 202
    job = _wait_job(api_client, created.json()["job_id"])
    assert job["status"] == "succeeded", job
    assert job["result"]["filename"].startswith("ostium-backup-")

    listing = api_client.get("/api/v1/backups", headers=headers).json()["backups"]
    assert len(listing) == 1
    backup = listing[0]
    assert backup["exists"] is True
    backup_path = settings.paths.backups_dir / backup["filename"]
    assert backup_path.is_file()
    assert backup["sha256"] == file_digest(backup_path)

    staged = api_client.post(f"/api/v1/backups/{backup['id']}/restore", json={}, headers=headers)
    assert staged.status_code == 202, staged.text
    assert staged.json()["staged"] is True
    assert staged.json()["restart_required"] is True
    assert (settings.paths.backups_dir / "restore-pending.bin").is_file()

    deleted = api_client.delete(f"/api/v1/backups/{backup['id']}", headers=headers)
    assert deleted.status_code == 200
    assert not backup_path.exists()
    assert api_client.get("/api/v1/backups", headers=headers).json()["backups"] == []


def test_encrypted_backup_wrong_password_and_missing_file(
    api_client: TestClient, session_token: str, settings: Settings
) -> None:
    headers = _headers(session_token)
    created = api_client.post(
        "/api/v1/backups", json={"password": "backup-password"}, headers=headers
    )
    assert created.status_code == 202
    job = _wait_job(api_client, created.json()["job_id"])
    assert job["status"] == "succeeded"
    backup_id = api_client.get("/api/v1/backups", headers=headers).json()["backups"][0]["id"]

    wrong = api_client.post(
        f"/api/v1/backups/{backup_id}/restore",
        json={"password": "wrong-password"},
        headers=headers,
    )
    assert wrong.status_code == 400
    assert wrong.json()["code"] == "invalid_password"

    missing_password = api_client.post(
        f"/api/v1/backups/{backup_id}/restore", json={}, headers=headers
    )
    assert missing_password.status_code == 400
    assert missing_password.json()["code"] == "password_required"

    right = api_client.post(
        f"/api/v1/backups/{backup_id}/restore",
        json={"password": "backup-password"},
        headers=headers,
    )
    assert right.status_code == 202

    # A deleted file or stale row is reported as not found.
    _sql(
        settings,
        "INSERT INTO backups (id,filename,size,sha256,encrypted,created_at) VALUES (?,?,?,?,?,?)",
        (
            "missing-file",
            "ostium-backup-missing.tar.gz",
            0,
            "0" * 64,
            0,
            "2026-01-01T00:00:00+00:00",
        ),
    )
    missing = api_client.post("/api/v1/backups/missing-file/restore", json={}, headers=headers)
    assert missing.status_code == 404
    assert (
        api_client.get("/api/v1/backups", headers=headers).json()["backups"][1]["exists"] is False
    )
    assert api_client.delete("/api/v1/backups/missing-file", headers=headers).status_code == 200


def test_backup_job_failure(api_client: TestClient, session_token: str, monkeypatch) -> None:
    headers = _headers(session_token)

    def fail(settings, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("backup failed")

    monkeypatch.setattr("ostium.services.backup.create_backup", fail)
    created = api_client.post(
        "/api/v1/backups", json={"acknowledge_plaintext": True}, headers=headers
    )
    job = _wait_job(api_client, created.json()["job_id"])
    assert job["status"] == "failed"
    assert "backup failed" in job["error"]


def test_file_digest(tmp_path: Path) -> None:
    path = tmp_path / "blob"
    path.write_bytes(b"x" * (1024 * 1024 + 5))
    digest = file_digest(path)
    import hashlib

    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()


def test_certificate_upload_use_and_delete(api_client: TestClient, session_token: str) -> None:
    headers = _headers(session_token)
    cert_pem, key_pem = _bundle("upload.example.com")
    uploaded = api_client.post(
        "/api/v1/certificates/upload",
        json={
            "domain": "upload.example.com",
            "cert_pem": cert_pem,
            "key_pem": key_pem,
            "auto_renew": False,
        },
        headers=headers,
    )
    assert uploaded.status_code == 200, uploaded.text
    certificate = uploaded.json()["certificate"]
    assert certificate["status"] == "ready"

    listing = api_client.get("/api/v1/certificates", headers=headers).json()["certificates"]
    assert len(listing) == 1

    used = api_client.post(
        f"/api/v1/certificates/{certificate['id']}/use",
        json={"kinds": ["hysteria2"]},
        headers=headers,
    )
    assert used.status_code == 200
    assert used.json()["ok"] is True

    deleted = api_client.delete(f"/api/v1/certificates/{certificate['id']}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert api_client.get("/api/v1/certificates", headers=headers).json()["certificates"] == []


class FakeIssuer:
    error: ClassVar[Exception | None] = None
    calls: ClassVar[list[str]] = []
    options: ClassVar[list[dict[str, object]]] = []

    def __init__(self, settings, store) -> None:
        pass

    async def issue(
        self, domain: str, *, staging: bool | None = None, email: str | None = None
    ) -> tuple[str, str]:
        FakeIssuer.calls.append(domain)
        FakeIssuer.options.append({"staging": staging, "email": email})
        if FakeIssuer.error:
            raise FakeIssuer.error
        return _bundle(domain)


def test_acme_issue_job_and_existing_row(
    api_client: TestClient, session_token: str, settings: Settings, monkeypatch
) -> None:
    headers = _headers(session_token)
    FakeIssuer.calls = []
    FakeIssuer.error = None
    monkeypatch.setattr("ostium.api.routes_certs.AcmeIssuer", FakeIssuer)
    monkeypatch.setattr("ostium.acme.client.AcmeIssuer", FakeIssuer)

    first = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "acme.example.com", "method": "acme"},
        headers=headers,
    )
    assert first.status_code == 202
    job = _wait_job(api_client, first.json()["job_id"])
    assert job["status"] == "succeeded", job
    certificates = api_client.get("/api/v1/certificates", headers=headers).json()["certificates"]
    assert certificates[0]["domain"] == "acme.example.com"
    assert certificates[0]["source"] == "acme"

    second = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "acme.example.com", "method": "acme", "auto_renew": False},
        headers=headers,
    )
    assert second.status_code == 202
    assert _wait_job(api_client, second.json()["job_id"])["status"] == "succeeded"
    certificates = api_client.get("/api/v1/certificates", headers=headers).json()["certificates"]
    assert len(certificates) == 1
    assert certificates[0]["auto_renew"] is False


def test_acme_issue_and_renew_job_apply_failure(
    api_client: TestClient, session_token: str, monkeypatch
) -> None:
    headers = _headers(session_token)
    FakeIssuer.calls = []
    FakeIssuer.error = None
    monkeypatch.setattr("ostium.api.routes_certs.AcmeIssuer", FakeIssuer)
    monkeypatch.setattr("ostium.acme.client.AcmeIssuer", FakeIssuer)

    async def fail(session):  # type: ignore[no-untyped-def]
        raise EngineError("apply failed", "engine_check_failed", 422)

    api_client.app.state.services.engine.apply_server = fail  # type: ignore[method-assign]

    issued = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "renew.example.com", "method": "acme"},
        headers=headers,
    )
    job = _wait_job(api_client, issued.json()["job_id"])
    assert job["status"] == "succeeded", job
    certificate = api_client.get("/api/v1/certificates", headers=headers).json()["certificates"][0]

    renewed = api_client.post(f"/api/v1/certificates/{certificate['id']}/renew", headers=headers)
    assert renewed.status_code == 202
    renewal = _wait_job(api_client, renewed.json()["job_id"])
    assert renewal["status"] == "succeeded", renewal
    logs = [item["message"] for item in api_client.app.state.services.bus.logs()]
    assert any("engine apply failed" in item for item in logs)
    assert any("renewed certificate apply failed" in item for item in logs)


def test_acme_issue_failure_job(api_client: TestClient, session_token: str, monkeypatch) -> None:
    headers = _headers(session_token)
    FakeIssuer.calls = []
    FakeIssuer.error = RuntimeError("acme failed")
    monkeypatch.setattr("ostium.api.routes_certs.AcmeIssuer", FakeIssuer)
    monkeypatch.setattr("ostium.acme.client.AcmeIssuer", FakeIssuer)
    response = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "bad-acme.example.com", "method": "acme"},
        headers=headers,
    )
    job = _wait_job(api_client, response.json()["job_id"])
    assert job["status"] == "failed"
    assert "acme failed" in job["error"]
