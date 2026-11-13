from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from ostium.config import Settings
from ostium.services.auth import make_local_login_token


def _auth(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


def test_setup_login_and_user_subscription_flow(api_client: TestClient, session_token: str) -> None:
    client = api_client
    assert client.get("/api/v1/auth/status").json()["initialized"] is True
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "admin"

    inbounds = client.get("/api/v1/inbounds").json()["inbounds"]
    kinds = {row["kind"]: row for row in inbounds}
    assert kinds["vless"]["enabled"] is True
    assert kinds["vless"]["params"]["public_key"]

    created = client.post(
        "/api/v1/users",
        json={"name": "alice", "quota_bytes": 1024**3, "quota_cycle": "monthly"},
        headers=_auth(session_token),
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    user = payload["user"]
    assert user["name"] == "alice"
    assert user["quota_cycle"] == "monthly"
    token = payload["subscription"]["formats"][0]["url"].split("/sub/")[1].split("?")[0]

    formats = {}
    for fmt in ("ostium", "base64", "clash", "singbox"):
        response = client.get(f"/sub/{token}?format={fmt}")
        assert response.status_code == 200, (fmt, response.text)
        assert response.headers["referrer-policy"] == "no-referrer"
        formats[fmt] = response.text
    profile = json.loads(formats["ostium"])
    assert profile["format"] == "ostium-profile"
    assert profile["endpoints"][0]["protocol"] == "vless-reality"
    decoded = base64.b64decode(formats["base64"]).decode()
    assert decoded.startswith("vless://")
    assert "proxies:" in formats["clash"]
    assert json.loads(formats["singbox"])["outbounds"][0]["type"] == "vless"

    listing = client.get("/api/v1/users").json()
    assert listing["total"] == 1

    disabled = client.patch(
        f"/api/v1/users/{user['id']}", json={"enabled": False}, headers=_auth(session_token)
    )
    assert disabled.status_code == 200
    assert client.get(f"/sub/{token}?format=ostium").status_code == 403
    assert client.get("/sub/does-not-exist?format=ostium").status_code == 404

    audit = client.get("/api/v1/audit").json()["entries"]
    actions = {entry["action"] for entry in audit}
    assert "user.created" in actions
    assert "user.updated" in actions


def test_subscription_header_supports_unicode_user_names(
    api_client: TestClient, session_token: str
) -> None:
    created = api_client.post(
        "/api/v1/users",
        json={"name": "香港用户", "quota_bytes": 1024**3},
        headers=_auth(session_token),
    )
    assert created.status_code == 201, created.text
    token = created.json()["subscription"]["formats"][0]["url"].split("/sub/")[1].split("?")[0]
    response = api_client.get(f"/sub/{token}?format=ostium")
    assert response.status_code == 200, response.text
    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    assert "ostium-subscription" in disposition


def test_client_only_endpoints_reject_server(api_client: TestClient, session_token: str) -> None:
    response = api_client.get("/api/v1/profiles")
    assert response.status_code == 400
    assert response.json()["code"] == "role_mismatch"


def test_csrf_is_required(api_client: TestClient, session_token: str) -> None:
    response = api_client.post("/api/v1/users", json={"name": "bob"})
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"


def test_login_after_logout(api_client: TestClient, session_token: str) -> None:
    client = api_client
    assert client.post("/api/v1/auth/logout", headers=_auth(session_token)).status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "verysecret123"},
    )
    assert login.status_code == 200, login.text
    assert client.get("/api/v1/auth/me").status_code == 200


def test_public_ui_requires_totp(api_client: TestClient, session_token: str) -> None:
    response = api_client.post(
        "/api/v1/settings/public-ui",
        json={"enabled": True, "domain": "example.com"},
        headers=_auth(session_token),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "totp_required"


def test_local_one_time_login(
    api_client: TestClient, settings: Settings, session_token: str
) -> None:
    client = api_client
    assert client.post("/api/v1/auth/logout", headers=_auth(session_token)).status_code == 200
    token = make_local_login_token(settings)
    response = client.get(f"/api/v1/auth/local-login?token={token}", follow_redirects=True)
    assert response.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.get("/api/v1/auth/local-login?token=bogus").status_code == 401


def test_rules_certificates_settings_and_system(api_client: TestClient, session_token: str) -> None:
    client = api_client
    headers = _auth(session_token)

    rule = client.post(
        "/api/v1/rules",
        json={"action": "direct", "match": {"domain_suffix": [".example.cn"]}, "note": "cn"},
        headers=headers,
    )
    assert rule.status_code == 201, rule.text
    rule_id = rule.json()["rule"]["id"]
    assert (
        client.post(
            "/api/v1/rules/test", json={"domain": "www.example.cn"}, headers=headers
        ).json()["rule"]["action"]
        == "direct"
    )
    assert (
        client.patch(
            f"/api/v1/rules/{rule_id}", json={"enabled": False}, headers=headers
        ).status_code
        == 200
    )
    assert client.delete(f"/api/v1/rules/{rule_id}", headers=headers).status_code == 200
    assert client.get("/api/v1/rule-sets").status_code == 200

    issued = client.post(
        "/api/v1/certificates/issue",
        json={"domain": "local.example.com", "method": "self-signed"},
        headers=headers,
    )
    assert issued.status_code == 202, issued.text
    certificate_id = issued.json()["certificate"]["id"]
    assert client.get("/api/v1/certificates").status_code == 200
    assert (
        client.post(
            f"/api/v1/certificates/{certificate_id}/use",
            json={"kinds": ["hysteria2"]},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.delete(f"/api/v1/certificates/{certificate_id}", headers=headers).status_code == 200
    )

    settings = client.get("/api/v1/settings").json()
    assert settings["general"]["role"] == "server"
    updated = client.patch("/api/v1/settings", json={"log_level": "warning"}, headers=headers)
    assert updated.status_code == 200
    token = client.post(
        "/api/v1/api-tokens", json={"name": "ci", "scopes": ["read"]}, headers=headers
    )
    assert token.status_code == 201
    assert (
        client.delete(f"/api/v1/api-tokens/{token.json()['id']}", headers=headers).status_code
        == 200
    )

    assert client.get("/api/v1/system/info").status_code == 200
    assert client.get("/api/v1/system/services").status_code == 200
    assert client.get("/api/v1/system/doctor").status_code == 200
    assert client.get("/api/v1/system/diagnostics").status_code == 200
    assert client.get("/api/v1/logs").status_code == 200
    assert client.get("/api/v1/jobs").status_code == 200
    assert client.get("/api/v1/alerts").status_code == 200
    assert client.get("/api/v1/audit").status_code == 200
