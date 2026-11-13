from __future__ import annotations

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import select

from ostium.config import Settings
from ostium.db.models import AdminUser
from ostium.db.session import create_engine, create_session_factory
from ostium.services.auth import make_local_login_token
from tests.conftest import csrf, setup_admin


def _headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


def test_api_docs_require_authentication(api_client: TestClient) -> None:
    assert api_client.get("/api/docs").status_code == 401
    assert api_client.get("/api/openapi.json").status_code == 401
    setup_admin(api_client)
    assert api_client.get("/api/docs").status_code == 200
    assert api_client.get("/api/openapi.json").status_code == 200


def test_local_login_token_is_single_use(api_client: TestClient, settings: Settings) -> None:
    setup_admin(api_client)
    token = make_local_login_token(settings)
    first = api_client.get(f"/api/v1/auth/local-login?token={token}", follow_redirects=False)
    assert first.status_code == 303
    second = api_client.get(f"/api/v1/auth/local-login?token={token}", follow_redirects=False)
    assert second.status_code == 401
    assert second.json()["code"] == "local_login_invalid"


def test_totp_start_does_not_activate_until_confirmed(
    api_client: TestClient, settings: Settings
) -> None:
    headers = _headers(setup_admin(api_client))
    started = api_client.post("/api/v1/auth/totp/start", headers=headers)
    assert started.status_code == 200
    secret = started.json()["secret"]
    codes = started.json()["recovery_codes"]

    async def _admin() -> AdminUser:
        engine = create_engine(settings.paths.db_path)
        factory = create_session_factory(engine)
        async with factory() as session:
            admin = (await session.execute(select(AdminUser))).scalar_one()
        await engine.dispose()
        return admin

    import asyncio

    admin = asyncio.run(_admin())
    assert admin.totp_secret_enc is None
    assert admin.recovery_codes_hash == []

    # Login still succeeds without a TOTP code because the secret is pending.
    login = api_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "verysecret123"},
        headers=_headers(csrf(api_client)),
    )
    assert login.status_code == 200

    confirmed = api_client.post(
        "/api/v1/auth/totp/confirm",
        json={"code": pyotp.TOTP(secret).now()},
        headers=headers,
    )
    assert confirmed.status_code == 200
    assert len(codes) == 10

    required = api_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "verysecret123"},
        headers=_headers(csrf(api_client)),
    )
    assert required.status_code == 401
    assert required.json()["code"] == "totp_required"


def test_totp_cancel_leaves_login_policy_unchanged(
    api_client: TestClient, settings: Settings
) -> None:
    headers = _headers(setup_admin(api_client))
    assert api_client.post("/api/v1/auth/totp/start", headers=headers).status_code == 200
    assert api_client.post("/api/v1/auth/totp/cancel", headers=headers).status_code == 200
    login = api_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "verysecret123"},
        headers=_headers(csrf(api_client)),
    )
    assert login.status_code == 200


def test_ui_ip_allowlist_blocks_and_allows(
    api_client: TestClient, session_token: str, settings: Settings, monkeypatch
) -> None:
    headers = _headers(session_token)
    created = api_client.post("/api/v1/users", json={"name": "allowed-sub"}, headers=headers)
    token = created.json()["subscription"]["formats"][0]["url"].split("/sub/")[1].split("?")[0]
    denied = api_client.patch(
        "/api/v1/settings", json={"ui_allowlist": ["203.0.113.0/24"]}, headers=headers
    )
    assert denied.status_code == 200
    assert api_client.get("/api/v1/users").status_code == 403
    # Subscription clients are not admin UI clients and must keep working.
    assert api_client.get(f"/sub/{token}").status_code == 200

    monkeypatch.setattr("ostium.api.app.client_ip", lambda request: "203.0.113.7")
    assert api_client.get("/api/v1/users").status_code == 200
    monkeypatch.setattr("ostium.api.app.client_ip", lambda request: "198.51.100.7")
    assert api_client.get("/api/v1/users").status_code == 403

    # Invalid CIDRs are rejected instead of silently widening access.
    monkeypatch.setattr("ostium.api.app.client_ip", lambda request: "203.0.113.7")
    invalid = api_client.patch(
        "/api/v1/settings", json={"ui_allowlist": ["not-a-cidr"]}, headers=headers
    )
    assert invalid.status_code == 400


def test_subscription_formats_and_inactive_status(
    api_client: TestClient, session_token: str, settings: Settings
) -> None:
    headers = _headers(session_token)
    created = api_client.post(
        "/api/v1/users", json={"name": "alice", "quota_bytes": 1000}, headers=headers
    )
    assert created.status_code == 201, created.text
    token = created.json()["subscription"]["formats"][0]["url"].split("/sub/")[1].split("?")[0]

    unknown = api_client.get(f"/sub/{token}?format=xml")
    assert unknown.status_code == 400

    user_id = created.json()["user"]["id"]
    disabled = api_client.patch(
        f"/api/v1/users/{user_id}", json={"enabled": False}, headers=headers
    )
    assert disabled.status_code == 200
    assert api_client.get(f"/sub/{token}").status_code == 403


def test_public_base_url_is_used_for_subscriptions(
    api_client: TestClient, session_token: str
) -> None:
    headers = _headers(session_token)
    updated = api_client.patch(
        "/api/v1/settings",
        json={"public_base_url": "https://edge.example.com"},
        headers=headers,
    )
    assert updated.status_code == 200
    created = api_client.post("/api/v1/users", json={"name": "bob"}, headers=headers)
    user_id = created.json()["user"]["id"]
    revealed = api_client.get(f"/api/v1/users/{user_id}/subscription?reveal=true", headers=headers)
    assert revealed.status_code == 200
    assert all(
        item["url"].startswith("https://edge.example.com/sub/")
        for item in revealed.json()["formats"]
    )


def test_bulk_user_export_returns_profiles(api_client: TestClient, session_token: str) -> None:
    headers = _headers(session_token)
    created = api_client.post("/api/v1/users", json={"name": "exporter"}, headers=headers)
    user_id = created.json()["user"]["id"]
    exported = api_client.post(
        "/api/v1/users/bulk",
        json={"action": "export", "ids": [user_id]},
        headers=headers,
    )
    assert exported.status_code == 200
    assert exported.json()["exports"][0]["user"] == "exporter"
    assert exported.json()["exports"][0]["profile"]["format"] == "ostium-profile"


def test_profile_activation_and_reorder(client_api: TestClient, client_settings: Settings) -> None:
    headers = _headers(setup_admin(client_api, role="client"))
    first = client_api.post(
        "/api/v1/profiles",
        json={"name": "A", "text": "vless://uuid@example.com:443?security=reality&pbk=x&sid=1#A"},
        headers=headers,
    )
    second = client_api.post(
        "/api/v1/profiles",
        json={"name": "B", "text": "vless://uuid@example.com:443?security=reality&pbk=x&sid=1#B"},
        headers=headers,
    )
    assert first.status_code == 201 and second.status_code == 201
    first_id = first.json()["profile"]["id"]
    second_id = second.json()["profile"]["id"]

    activated = client_api.post(f"/api/v1/profiles/{first_id}/activate", headers=headers)
    assert activated.status_code == 200
    listing = client_api.get("/api/v1/profiles").json()
    assert listing["active_profile_id"] == first_id
    assert next(item for item in listing["profiles"] if item["id"] == first_id)["active"] is True

    reordered = client_api.post(
        "/api/v1/profiles/reorder", json={"ids": [second_id, first_id]}, headers=headers
    )
    assert reordered.status_code == 200
    invalid = client_api.post(
        "/api/v1/profiles/reorder", json={"ids": [second_id]}, headers=headers
    )
    assert invalid.status_code == 422


def test_inbound_tcp_port_conflict(api_client: TestClient, session_token: str) -> None:
    headers = _headers(session_token)
    assert (
        api_client.patch("/api/v1/inbounds/vless", json={"port": 9443}, headers=headers).status_code
        == 200
    )
    assert (
        api_client.patch(
            "/api/v1/inbounds/shadowsocks",
            json={"port": 9443, "enabled": True},
            headers=headers,
        ).status_code
        == 409
    )


def test_certificate_route_validation(api_client: TestClient, session_token: str) -> None:
    headers = _headers(session_token)
    invalid = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "not_a_domain", "method": "self-signed"},
        headers=headers,
    )
    assert invalid.status_code == 400

    upload = api_client.post(
        "/api/v1/certificates/upload",
        json={"domain": "vpn.example.com", "cert_pem": "nope", "key_pem": "nope"},
        headers=headers,
    )
    assert upload.status_code == 400

    created = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "self.example.com", "method": "self-signed"},
        headers=headers,
    )
    assert created.status_code == 202
    certificate_id = created.json()["certificate"]["id"]
    renew = api_client.post(f"/api/v1/certificates/{certificate_id}/renew", headers=headers)
    assert renew.status_code == 400

    used = api_client.post(
        f"/api/v1/certificates/{certificate_id}/use",
        json={"kinds": ["vless"]},
        headers=headers,
    )
    assert used.status_code == 400
    assert api_client.delete("/api/v1/certificates/missing", headers=headers).status_code == 404


def test_acme_issue_forwards_staging_and_email(
    api_client: TestClient, session_token: str, monkeypatch
) -> None:
    headers = _headers(session_token)
    from tests.integration.test_api_backups_certs import FakeIssuer, _wait_job

    FakeIssuer.calls = []
    FakeIssuer.options = []
    FakeIssuer.error = None
    monkeypatch.setattr("ostium.api.routes_certs.AcmeIssuer", FakeIssuer)
    issued = api_client.post(
        "/api/v1/certificates/issue",
        json={
            "domain": "staging.example.com",
            "method": "acme",
            "staging": True,
            "email": "ops@example.com",
        },
        headers=headers,
    )
    assert issued.status_code == 202
    assert _wait_job(api_client, issued.json()["job_id"])["status"] == "succeeded"
    assert FakeIssuer.options[-1] == {"staging": True, "email": "ops@example.com"}


def test_acme_reissue_after_failed_certificate(
    api_client: TestClient, session_token: str, monkeypatch
) -> None:
    headers = _headers(session_token)
    from tests.integration.test_api_backups_certs import FakeIssuer, _wait_job

    FakeIssuer.calls = []
    FakeIssuer.options = []
    FakeIssuer.error = RuntimeError("first attempt failed")
    monkeypatch.setattr("ostium.api.routes_certs.AcmeIssuer", FakeIssuer)
    first = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "retry.example.com", "method": "acme"},
        headers=headers,
    )
    assert first.status_code == 202
    assert _wait_job(api_client, first.json()["job_id"])["status"] == "failed"
    failed = next(
        item
        for item in api_client.get("/api/v1/certificates", headers=headers).json()["certificates"]
        if item["domain"] == "retry.example.com"
    )
    assert failed["status"] == "error"

    FakeIssuer.error = None
    second = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "retry.example.com", "method": "acme"},
        headers=headers,
    )
    assert second.status_code == 202
    assert _wait_job(api_client, second.json()["job_id"])["status"] == "succeeded"
    ready = next(
        item
        for item in api_client.get("/api/v1/certificates", headers=headers).json()["certificates"]
        if item["domain"] == "retry.example.com"
    )
    assert ready["status"] == "ready"


def test_acme_reissue_failure_keeps_ready_certificate(
    api_client: TestClient, session_token: str, monkeypatch
) -> None:
    headers = _headers(session_token)
    from tests.integration.test_api_backups_certs import FakeIssuer, _wait_job

    FakeIssuer.calls = []
    FakeIssuer.options = []
    FakeIssuer.error = None
    monkeypatch.setattr("ostium.api.routes_certs.AcmeIssuer", FakeIssuer)
    first = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "stable.example.com", "method": "acme"},
        headers=headers,
    )
    assert _wait_job(api_client, first.json()["job_id"])["status"] == "succeeded"

    FakeIssuer.error = RuntimeError("renewal failed")
    second = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "stable.example.com", "method": "acme"},
        headers=headers,
    )
    assert second.status_code == 202
    assert _wait_job(api_client, second.json()["job_id"])["status"] == "failed"
    after = next(
        item
        for item in api_client.get("/api/v1/certificates", headers=headers).json()["certificates"]
        if item["domain"] == "stable.example.com"
    )
    assert after["status"] == "ready"
    assert after["stored_status"] == "ready"
    assert "renewal failed" in (after["last_error"] or "")


def test_acme_job_tolerates_deleted_certificate_row(
    api_client: TestClient, session_token: str, monkeypatch
) -> None:
    headers = _headers(session_token)
    from sqlalchemy import select

    from ostium.db.models import Certificate
    from tests.integration.test_api_backups_certs import FakeIssuer, _wait_job

    FakeIssuer.calls = []
    FakeIssuer.options = []
    FakeIssuer.error = None
    monkeypatch.setattr("ostium.api.routes_certs.AcmeIssuer", FakeIssuer)

    async def broken_import(session, settings, *, domain, cert_pem, key_pem, source):
        row = (
            await session.execute(select(Certificate).where(Certificate.domain == domain))
        ).scalar_one_or_none()
        if row is not None:
            await session.delete(row)
            await session.commit()
        raise RuntimeError("row vanished")

    monkeypatch.setattr("ostium.api.routes_certs.cert_service.import_manual", broken_import)
    issued = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "vanish.example.com", "method": "acme"},
        headers=headers,
    )
    assert issued.status_code == 202
    job = _wait_job(api_client, issued.json()["job_id"])
    assert job["status"] == "failed"
    assert "row vanished" in (job["error"] or "")


def test_certificate_renewal_failure_keeps_ready_status(
    api_client: TestClient, session_token: str, monkeypatch
) -> None:
    headers = _headers(session_token)
    from tests.integration.test_api_backups_certs import FakeIssuer, _wait_job

    FakeIssuer.calls = []
    FakeIssuer.error = None
    monkeypatch.setattr("ostium.api.routes_certs.AcmeIssuer", FakeIssuer)
    issued = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "keep.example.com", "method": "acme"},
        headers=headers,
    )
    assert issued.status_code == 202
    assert _wait_job(api_client, issued.json()["job_id"])["status"] == "succeeded"
    certificate = next(
        item
        for item in api_client.get("/api/v1/certificates", headers=headers).json()["certificates"]
        if item["domain"] == "keep.example.com"
    )
    assert certificate["status"] == "ready"

    FakeIssuer.error = RuntimeError("ACME down")
    renewed = api_client.post(f"/api/v1/certificates/{certificate['id']}/renew", headers=headers)
    assert renewed.status_code == 202
    assert _wait_job(api_client, renewed.json()["job_id"])["status"] == "failed"
    after = next(
        item
        for item in api_client.get("/api/v1/certificates", headers=headers).json()["certificates"]
        if item["id"] == certificate["id"]
    )
    assert after["status"] == "ready"
    assert "ACME down" in (after["last_error"] or "")
