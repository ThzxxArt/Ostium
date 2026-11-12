from __future__ import annotations

import pyotp
from fastapi.testclient import TestClient

from ostium.config import Settings
from tests.conftest import csrf, setup_admin


def _headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


def _enable_totp(client: TestClient, headers: dict[str, str]) -> str:
    start = client.post("/api/v1/auth/totp/start", headers=headers).json()
    code = pyotp.TOTP(start["secret"]).now()
    assert (
        client.post("/api/v1/auth/totp/confirm", json={"code": code}, headers=headers).status_code
        == 200
    )
    return start["secret"]


def test_settings_read_and_patch(api_client: TestClient, settings: Settings) -> None:
    token = setup_admin(api_client)
    headers = _headers(token)

    initial = api_client.get("/api/v1/settings").json()
    assert initial["general"]["role"] == "server"
    assert initial["general"]["routing_mode"] == "smart"
    assert initial["security"]["trusted_hosts"] == ["localhost", "127.0.0.1", "::1"]
    assert initial["notifications"]["enabled"] is True
    assert initial["maintenance"]["update_channel"] == "stable"

    patched = api_client.patch(
        "/api/v1/settings",
        json={
            "mixed_port": 7899,
            "allow_lan": True,
            "log_level": "debug",
            "trusted_hosts": ["localhost", "example.com"],
            "routing_mode": "global",
            "auto_connect": True,
            "auto_reconnect": False,
            "webhook_url": "https://hooks.example.com/x",
            "webhook_secret": "secret",
            "update_channel": "beta",
            "audit_retention_days": 30,
            "traffic_retention_days": 90,
            "auto_backup": True,
            "notifications_enabled": False,
        },
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["restart_required"] is True
    assert settings.mixed_port == 7899
    assert settings.allow_lan is True
    assert settings.log_level == "debug"
    assert settings.trusted_hosts == ["localhost", "example.com"]
    assert settings.auto_connect is True
    assert settings.auto_reconnect is False

    reread = api_client.get("/api/v1/settings").json()
    assert reread["general"]["allow_lan"] is True
    assert reread["general"]["routing_mode"] == "global"
    assert reread["notifications"]["has_webhook_secret"] is True
    assert reread["notifications"]["enabled"] is False
    assert reread["maintenance"]["update_channel"] == "beta"
    assert reread["maintenance"]["audit_retention_days"] == 30
    assert reread["maintenance"]["traffic_retention_days"] == 90
    assert reread["maintenance"]["auto_backup"] is True

    invalid = api_client.patch("/api/v1/settings", json={"mixed_port": 80}, headers=headers)
    assert invalid.status_code == 422


def test_allow_lan_applies_client_config(client_api: TestClient, monkeypatch) -> None:
    token = setup_admin(client_api, role="client")
    headers = _headers(token)
    services = client_api.app.state.services
    calls: list[bool] = []

    async def apply(session) -> dict:  # type: ignore[no-untyped-def]
        calls.append(True)
        return {"status": {"revision": "lan-revision"}}

    monkeypatch.setattr(services.engine, "apply_client", apply)
    response = client_api.patch("/api/v1/settings", json={"allow_lan": True}, headers=headers)
    assert response.status_code == 200, response.text
    assert services.settings.allow_lan is True
    assert calls == [True]
    assert response.json()["applied"] is True


def test_settings_save_failure(api_client: TestClient, monkeypatch) -> None:
    token = setup_admin(api_client)
    headers = _headers(token)

    def fail(self: Settings, path=None) -> None:
        raise OSError("read-only")

    monkeypatch.setattr(Settings, "save", fail)
    response = api_client.patch("/api/v1/settings", json={"log_level": "error"}, headers=headers)
    assert response.status_code == 500
    assert response.json()["code"] == "settings_write_failed"


def test_public_ui_requires_totp_domain_and_certificate(api_client: TestClient) -> None:
    token = setup_admin(api_client)
    headers = _headers(token)

    totp = api_client.post("/api/v1/settings/public-ui", json={"enabled": True}, headers=headers)
    assert totp.status_code == 409
    assert totp.json()["code"] == "totp_required"

    _enable_totp(api_client, headers)
    headers = _headers(csrf(api_client))

    domain = api_client.post("/api/v1/settings/public-ui", json={"enabled": True}, headers=headers)
    assert domain.status_code == 400
    assert domain.json()["code"] == "domain_required"

    certificate = api_client.post(
        "/api/v1/settings/public-ui",
        json={"enabled": True, "domain": "ui.example.com"},
        headers=headers,
    )
    assert certificate.status_code == 409
    assert certificate.json()["code"] == "certificate_required"


def test_public_ui_enable_and_disable(api_client: TestClient, settings: Settings) -> None:
    token = setup_admin(api_client)
    headers = _headers(token)
    _enable_totp(api_client, headers)
    headers = _headers(csrf(api_client))
    assert (
        api_client.post(
            "/api/v1/certificates/issue",
            json={"domain": "ui.example.com", "method": "self-signed"},
            headers=headers,
        ).status_code
        == 202
    )

    enabled = api_client.post(
        "/api/v1/settings/public-ui",
        json={"enabled": True, "domain": "ui.example.com"},
        headers=headers,
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["public_ui"] is True
    assert settings.public_ui is True
    assert settings.secure_cookies is True
    assert "ui.example.com" in settings.trusted_hosts
    server = api_client.get("/api/v1/settings").json()
    assert server["general"]["public_ui"] is True
    assert server["general"]["domain"] == "ui.example.com"

    disabled = api_client.post(
        "/api/v1/settings/public-ui", json={"enabled": False}, headers=headers
    )
    assert disabled.status_code == 200
    assert settings.public_ui is False
    assert settings.secure_cookies is False


def test_public_ui_disable_handles_non_dict_setting(api_client: TestClient, monkeypatch) -> None:
    token = setup_admin(api_client)
    headers = _headers(token)
    _enable_totp(api_client, headers)
    headers = _headers(csrf(api_client))
    api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "ui.example.com", "method": "self-signed"},
        headers=headers,
    )

    async def not_a_dict(session, key, default=None):  # type: ignore[no-untyped-def]
        return "broken"

    monkeypatch.setattr("ostium.api.routes_settings.get_setting", not_a_dict)
    response = api_client.post(
        "/api/v1/settings/public-ui",
        json={"enabled": True, "domain": "ui.example.com"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["public_ui"] is True


def test_api_tokens(api_client: TestClient) -> None:
    token = setup_admin(api_client)
    headers = _headers(token)
    created = api_client.post(
        "/api/v1/api-tokens",
        json={"name": "ci", "scopes": ["read", "write"]},
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["token"].startswith("ost_")
    listing = api_client.get("/api/v1/api-tokens").json()["tokens"]
    assert listing[0]["name"] == "ci"
    assert listing[0]["revoked"] is False

    revoked = api_client.delete(f"/api/v1/api-tokens/{created.json()['id']}", headers=headers)
    assert revoked.status_code == 200
    assert api_client.get("/api/v1/api-tokens").json()["tokens"][0]["revoked"] is True

    missing = api_client.delete("/api/v1/api-tokens/missing", headers=headers)
    assert missing.status_code == 404
