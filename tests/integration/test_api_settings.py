from __future__ import annotations

import pyotp
import pytest
from fastapi.testclient import TestClient

from ostium.config import Mode, Settings
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
    assert set(initial["security"]["trusted_hosts"]) == {
        "localhost",
        "127.0.0.1",
        "::1",
        "example.com",
    }
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


def test_allow_lan_apply_failure_restores_previous_state(
    client_api: TestClient, monkeypatch
) -> None:
    token = setup_admin(client_api, role="client")
    headers = _headers(token)
    services = client_api.app.state.services

    async def apply(session) -> dict:  # type: ignore[no-untyped-def]
        raise RuntimeError("core unreachable")

    monkeypatch.setattr(services.engine, "apply_client", apply)
    response = client_api.patch("/api/v1/settings", json={"allow_lan": True}, headers=headers)
    assert response.status_code == 502, response.text
    assert response.json()["code"] == "lan_apply_failed"
    assert services.settings.allow_lan is False
    # The on-disk value must match the in-memory switch.
    assert "allow_lan = true" not in services.settings.config_file.read_text()


def test_allow_lan_rejects_tun_mode(client_api: TestClient) -> None:
    token = setup_admin(client_api, role="client")
    headers = _headers(token)
    services = client_api.app.state.services
    services.settings.tun_enabled = True

    response = client_api.patch("/api/v1/settings", json={"allow_lan": True}, headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "mode_conflict"
    assert services.settings.allow_lan is False


def test_mixed_port_change_moves_the_system_proxy(
    client_api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = setup_admin(client_api, role="client")
    headers = _headers(token)
    services = client_api.app.state.services
    services.settings.mode = Mode.SYSTEM_PROXY
    enabled: list[tuple[str, int]] = []

    async def apply(session) -> dict:  # type: ignore[no-untyped-def]
        return {"status": {"revision": "port-revision"}}

    class Proxy:
        def status(self) -> dict:
            return {"enabled": True, "stale": False}

        def enable(self, host: str, port: int) -> dict:
            enabled.append((host, port))
            return {"enabled": True}

    monkeypatch.setattr(services.engine, "apply_client", apply)
    monkeypatch.setattr(services, "proxy_manager", Proxy())
    response = client_api.patch("/api/v1/settings", json={"mixed_port": 7899}, headers=headers)
    assert response.status_code == 200, response.text
    assert services.settings.mixed_port == 7899
    # The old WinINET value points at a closed port; the update must move it.
    assert enabled == [("127.0.0.1", 7899)]


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
    assert settings.host == "0.0.0.0"
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
    assert settings.host == "127.0.0.1"


def test_public_ui_disable_restores_a_previous_secure_cookie_policy(
    api_client: TestClient, settings: Settings
) -> None:
    token = setup_admin(api_client)
    headers = _headers(token)
    _enable_totp(api_client, headers)
    headers = _headers(csrf(api_client))
    api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "ui.example.com", "method": "self-signed"},
        headers=headers,
    )
    # Simulate an operator that already terminates HTTPS in Nginx and enabled
    # secure cookies before turning on the Public UI.
    settings.secure_cookies = True
    settings.save()

    enabled = api_client.post(
        "/api/v1/settings/public-ui",
        json={"enabled": True, "domain": "ui.example.com"},
        headers=headers,
    )
    assert enabled.status_code == 200, enabled.text
    disabled = api_client.post(
        "/api/v1/settings/public-ui", json={"enabled": False}, headers=headers
    )
    assert disabled.status_code == 200, disabled.text
    assert settings.secure_cookies is True


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

    naive_expiry = api_client.post(
        "/api/v1/api-tokens",
        json={
            "name": "naive",
            "scopes": ["read"],
            "expires_at": "2027-01-01T00:00:00",
        },
        headers=headers,
    )
    assert naive_expiry.status_code == 422
    assert "timezone" in naive_expiry.text

    listing = api_client.get("/api/v1/api-tokens").json()["tokens"]
    assert listing[0]["name"] == "ci"
    assert listing[0]["revoked"] is False

    invalid_scope = api_client.post(
        "/api/v1/api-tokens",
        json={"name": "bad", "scopes": ["admin"]},
        headers=headers,
    )
    assert invalid_scope.status_code == 422

    read_only = api_client.post(
        "/api/v1/api-tokens",
        json={"name": "readonly", "scopes": ["read"]},
        headers=headers,
    )
    read_token = read_only.json()["token"]
    assert (
        api_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {read_token}"}
        ).status_code
        == 200
    )
    denied = api_client.post(
        "/api/v1/api-tokens",
        json={"name": "nope", "scopes": ["read"]},
        headers={"Authorization": f"Bearer {read_token}"},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "insufficient_scope"

    revoked = api_client.delete(f"/api/v1/api-tokens/{created.json()['id']}", headers=headers)
    assert revoked.status_code == 200
    tokens = {item["name"]: item for item in api_client.get("/api/v1/api-tokens").json()["tokens"]}
    assert tokens["ci"]["revoked"] is True

    missing = api_client.delete("/api/v1/api-tokens/missing", headers=headers)
    assert missing.status_code == 404


def test_public_ui_enable_repairs_the_default_subscription_port(
    api_client: TestClient, settings: Settings
) -> None:
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
    # ``ostium init --domain`` records the 443 form before Public UI exists.
    stored = api_client.patch(
        "/api/v1/settings",
        json={"public_base_url": "https://ui.example.com"},
        headers=headers,
    )
    assert stored.status_code == 200, stored.text

    enabled = api_client.post(
        "/api/v1/settings/public-ui",
        json={"enabled": True, "domain": "ui.example.com"},
        headers=headers,
    )
    assert enabled.status_code == 200, enabled.text
    general = api_client.get("/api/v1/settings").json()["general"]
    assert general["public_base_url"] == f"https://ui.example.com:{settings.port}"


def test_public_ui_enable_keeps_an_explicit_base_url(
    api_client: TestClient, settings: Settings
) -> None:
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
    explicit = "https://edge.example.net:9443"
    api_client.patch("/api/v1/settings", json={"public_base_url": explicit}, headers=headers)
    enabled = api_client.post(
        "/api/v1/settings/public-ui",
        json={"enabled": True, "domain": "ui.example.com"},
        headers=headers,
    )
    assert enabled.status_code == 200, enabled.text
    general = api_client.get("/api/v1/settings").json()["general"]
    assert general["public_base_url"] == explicit


def test_public_ui_certificate_cannot_be_deleted_while_in_use(
    api_client: TestClient, settings: Settings
) -> None:
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
    certificates = api_client.get("/api/v1/certificates").json()["certificates"]
    certificate_id = next(item["id"] for item in certificates if item["domain"] == "ui.example.com")
    blocked = api_client.delete(f"/api/v1/certificates/{certificate_id}", headers=headers)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "certificate_in_use"

    # A certificate that is not serving the Public UI can still be deleted.
    assert (
        api_client.post(
            "/api/v1/certificates/issue",
            json={"domain": "other.example.com", "method": "self-signed"},
            headers=headers,
        ).status_code
        == 202
    )
    certificates = api_client.get("/api/v1/certificates").json()["certificates"]
    other_id = next(item["id"] for item in certificates if item["domain"] == "other.example.com")
    deleted = api_client.delete(f"/api/v1/certificates/{other_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"server_dns_mode": "system"},
        {"server_dns_doh_url": "http://1.1.1.1/dns-query"},
        {"system_proxy_fail_open_seconds": 1},
        {"trusted_hosts": [""]},
        {"ui_allowlist": ["not-a-cidr"]},
        {"routing_mode": "bogus"},
        {"webhook_url": "ftp://example.com/hook"},
        {"public_base_url": "ftp://example.com"},
    ],
)
def test_settings_reject_invalid_values(api_client: TestClient, payload: dict[str, object]) -> None:
    token = setup_admin(api_client)
    response = api_client.patch("/api/v1/settings", json=payload, headers=_headers(token))
    assert response.status_code == 400, response.text
