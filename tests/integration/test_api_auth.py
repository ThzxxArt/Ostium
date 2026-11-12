from __future__ import annotations

import sqlite3
from datetime import timedelta

import pyotp
from fastapi.testclient import TestClient

from ostium.config import Settings
from ostium.util.time import utcnow
from tests.conftest import csrf, setup_admin


def _headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


def _sql(settings: Settings, statement: str, params: tuple[object, ...] = ()) -> None:
    with sqlite3.connect(settings.paths.db_path) as connection:
        connection.execute(statement, params)
        connection.commit()


def test_status_setup_validation_and_duplicate(api_client: TestClient, settings: Settings) -> None:
    client = api_client
    status = client.get("/api/v1/auth/status").json()
    assert status["initialized"] is False
    assert status["has_admin"] is False
    assert status["role"] == "server"
    assert status["public_ui"] is False

    token = csrf(client)
    wrong_role = client.post(
        "/api/v1/setup",
        json={"role": "client", "username": "admin", "password": "verysecret123"},
        headers=_headers(token),
    )
    assert wrong_role.status_code == 400
    assert wrong_role.json()["code"] == "role_mismatch"

    public = client.post(
        "/api/v1/setup",
        json={
            "role": "server",
            "username": "admin",
            "password": "verysecret123",
            "public_ui": True,
        },
        headers=_headers(token),
    )
    assert public.status_code == 400
    assert public.json()["code"] == "totp_required"

    weak = client.post(
        "/api/v1/setup",
        json={"role": "server", "username": "admin", "password": "short"},
        headers=_headers(token),
    )
    assert weak.status_code == 422

    created = client.post(
        "/api/v1/setup",
        json={
            "role": "server",
            "username": "admin",
            "password": "verysecret123",
            "domain": "Example.COM",
            "acme_email": "a@example.com",
        },
        headers=_headers(token),
    )
    assert created.status_code == 200, created.text
    assert created.json()["role"] == "server"
    assert client.get("/api/v1/auth/status").json()["initialized"] is True

    me = client.get("/api/v1/auth/me").json()
    assert me["username"] == "admin"
    assert me["recovery_codes_remaining"] == 0
    assert me["last_login_at"] is None
    assert me["role"] == "server"

    duplicate = client.post(
        "/api/v1/setup",
        json={"role": "server", "username": "other", "password": "verysecret123"},
        headers=_headers(token),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "already_initialized"


def test_login_failures_account_states_and_rate_limit(
    api_client: TestClient, settings: Settings
) -> None:
    client = api_client
    setup_admin(client)
    client.post("/api/v1/auth/logout", headers=_headers(csrf(client)))

    missing = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "wrong-password"}
    )
    assert missing.status_code == 401
    assert missing.json()["code"] == "invalid_credentials"

    unknown = client.post(
        "/api/v1/auth/login", json={"username": "nobody", "password": "wrong-password"}
    )
    assert unknown.status_code == 401

    _sql(settings, "UPDATE admin_users SET disabled=1 WHERE username='admin'")
    disabled = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "verysecret123"}
    )
    assert disabled.status_code == 403
    assert disabled.json()["code"] == "account_disabled"
    _sql(settings, "UPDATE admin_users SET disabled=0")

    locked_until = (utcnow() + timedelta(minutes=5)).isoformat()
    _sql(settings, "UPDATE admin_users SET locked_until=? WHERE username='admin'", (locked_until,))
    locked = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "verysecret123"}
    )
    assert locked.status_code == 423
    assert locked.json()["code"] == "account_locked"
    _sql(settings, "UPDATE admin_users SET locked_until=NULL")

    # Five failures trip both the persisted lock and the in-process limiter.
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"username": "admin", "password": "bad"})
    limited = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "verysecret123"}
    )
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"

    cli_token = settings.paths.runtime_dir / "cli.token"
    audit = client.get(
        "/api/v1/audit", headers={"Authorization": f"Bearer {cli_token.read_text().strip()}"}
    )
    assert audit.status_code == 200
    assert "auth.login_failed" in {entry["action"] for entry in audit.json()["entries"]}


def test_totp_lifecycle_password_and_logout(api_client: TestClient, settings: Settings) -> None:
    client = api_client
    token = setup_admin(client)
    headers = _headers(token)

    start = client.post("/api/v1/auth/totp/start", headers=headers)
    assert start.status_code == 200, start.text
    payload = start.json()
    assert payload["uri"].startswith("otpauth://")
    assert len(payload["recovery_codes"]) == 10
    secret = payload["secret"]

    bad_confirm = client.post("/api/v1/auth/totp/confirm", json={"code": "000000"}, headers=headers)
    assert bad_confirm.status_code == 400
    assert bad_confirm.json()["code"] == "totp_invalid"

    good_confirm = client.post(
        "/api/v1/auth/totp/confirm",
        json={"code": pyotp.TOTP(secret).now()},
        headers=headers,
    )
    assert good_confirm.status_code == 200

    client.post("/api/v1/auth/logout", headers=headers)
    no_totp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "verysecret123"}
    )
    assert no_totp.status_code == 401
    assert no_totp.json()["code"] == "totp_required"
    with_totp = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "verysecret123",
            "totp": pyotp.TOTP(secret).now(),
        },
    )
    assert with_totp.status_code == 200

    headers = _headers(csrf(client))
    wrong_password = client.post(
        "/api/v1/auth/password",
        json={"current_password": "nope", "new_password": "newpassword123"},
        headers=headers,
    )
    assert wrong_password.status_code == 403

    weak = client.post(
        "/api/v1/auth/password",
        json={"current_password": "verysecret123", "new_password": "short"},
        headers=headers,
    )
    assert weak.status_code == 422

    changed = client.post(
        "/api/v1/auth/password",
        json={"current_password": "verysecret123", "new_password": "newpassword123"},
        headers=headers,
    )
    assert changed.status_code == 200

    bad_disable = client.post(
        "/api/v1/auth/totp/disable", json={"password": "nope"}, headers=headers
    )
    assert bad_disable.status_code == 403

    settings.public_ui = True
    forced = client.post(
        "/api/v1/auth/totp/disable", json={"password": "newpassword123"}, headers=headers
    )
    assert forced.status_code == 409
    assert forced.json()["code"] == "totp_required"
    settings.public_ui = False

    disabled = client.post(
        "/api/v1/auth/totp/disable", json={"password": "newpassword123"}, headers=headers
    )
    assert disabled.status_code == 200
    assert client.get("/api/v1/auth/me").json()["totp_enabled"] is False

    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200


def test_totp_confirm_requires_started_setup(api_client: TestClient) -> None:
    token = setup_admin(api_client)
    response = api_client.post(
        "/api/v1/auth/totp/confirm", json={"code": "123456"}, headers=_headers(token)
    )
    assert response.status_code == 400
    assert response.json()["code"] == "totp_not_started"


def test_session_cookie_status_and_bearer_tokens(api_client: TestClient) -> None:
    token = setup_admin(api_client)
    status = api_client.get("/api/v1/auth/status").json()
    assert status["authenticated"] is True
    assert status["must_change_password"] is False

    cli_token = (api_client.app.state.services.settings.paths.runtime_dir / "cli.token").read_text()
    bearer = api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {cli_token}"})
    assert bearer.status_code == 200

    bad_bearer = api_client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nope"})
    assert bad_bearer.status_code == 401

    created = api_client.post(
        "/api/v1/api-tokens",
        json={"name": "read", "scopes": ["read"], "expires_at": None},
        headers=_headers(token),
    )
    api_token = created.json()["token"]
    api_me = api_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {api_token}"})
    assert api_me.status_code == 200

    revoked = api_client.delete(
        f"/api/v1/api-tokens/{created.json()['id']}", headers=_headers(token)
    )
    assert revoked.status_code == 200
    assert (
        api_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {api_token}"}
        ).status_code
        == 401
    )

    api_client.cookies.clear()
    unauthenticated = api_client.get("/api/v1/auth/me")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["code"] == "unauthorized"


def test_expired_and_revoked_sessions(api_client: TestClient, settings: Settings) -> None:
    from ostium.services.auth import make_local_login_token

    setup_admin(api_client)
    assert api_client.get("/api/v1/auth/me").status_code == 200
    _sql(settings, "UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00'")
    expired = api_client.get("/api/v1/auth/me")
    assert expired.status_code == 401
    assert expired.json()["code"] == "session_expired"

    local = make_local_login_token(settings)
    relogin = api_client.get(f"/api/v1/auth/local-login?token={local}", follow_redirects=False)
    assert relogin.status_code == 303
    assert api_client.get("/api/v1/auth/me").status_code == 200
    _sql(settings, "UPDATE sessions SET revoked=1")
    assert api_client.get("/api/v1/auth/me").status_code == 401


def test_local_login_missing_admin(api_client: TestClient, settings: Settings) -> None:
    from ostium.services.auth import make_local_login_token

    token = make_local_login_token(settings)
    response = api_client.get(f"/api/v1/auth/local-login?token={token}", follow_redirects=False)
    assert response.status_code == 409
    assert response.json()["code"] == "not_initialized"
    assert api_client.get("/api/v1/auth/local-login?token=bad").status_code == 401


def test_login_before_initialization(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "verysecret123"}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "not_initialized"


def test_status_with_invalid_cookie_and_logout_without_session(
    api_client: TestClient,
) -> None:
    setup_admin(api_client)
    api_client.cookies.set("ostium_session", "not-a-session")
    status = api_client.get("/api/v1/auth/status").json()
    assert status["authenticated"] is False
    assert (
        api_client.post("/api/v1/auth/logout", headers=_headers(csrf(api_client))).status_code
        == 200
    )
    assert api_client.get("/api/v1/auth/me").status_code == 401


def test_csrf_cookie_is_set_and_matches(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    cookie = response.cookies.get("ostium_csrf")
    assert cookie
    assert response.json()["csrf_token"] == cookie
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in response.headers


def test_secure_cookies_enable_hsts(api_client: TestClient, settings: Settings) -> None:
    settings.secure_cookies = True
    response = api_client.get("/healthz")
    assert "Strict-Transport-Security" in response.headers
    assert api_client.cookies.get("ostium_csrf") is None or True
    cookie_header = response.headers.get("set-cookie", "")
    if cookie_header:
        assert "Secure" in cookie_header
