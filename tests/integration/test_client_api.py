from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import csrf, setup_admin

VLESS = (
    "vless://2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e@vpn.example.com:443"
    "?encryption=none&security=reality&sni=www.apple.com&fp=chrome"
    "&pbk=Bs2KLXAKuw5pGFpBIwnyt896Y8mhNJHewMHHY0en6hM&sid=55e1651e#HK"
)


def test_client_profile_flow(client_api: TestClient) -> None:
    token = setup_admin(client_api, role="client")
    headers = {"X-CSRF-Token": token}
    assert client_api.get("/api/v1/auth/me").json()["role"] == "client"

    created = client_api.post(
        "/api/v1/profiles",
        json={"name": "HK", "text": VLESS},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    profile = created.json()["profile"]
    assert len(profile["endpoints"]) == 1
    profile_id = profile["id"]

    assert client_api.get("/api/v1/profiles").json()["profiles"][0]["name"] == "HK"
    updated = client_api.patch(
        f"/api/v1/profiles/{profile_id}",
        json={"selected_endpoint": profile["endpoints"][0]["tag"]},
        headers=headers,
    )
    assert updated.status_code == 200
    exported = client_api.get(f"/api/v1/profiles/{profile_id}/export")
    assert exported.status_code == 200
    assert exported.json()["endpoints"][0]["protocol"] == "vless-reality"
    tested = client_api.get(f"/api/v1/profiles/{profile_id}/test")
    assert tested.status_code == 200
    assert tested.json()["results"][0]["tag"] == profile["endpoints"][0]["tag"]
    assert client_api.delete(f"/api/v1/profiles/{profile_id}", headers=headers).status_code == 200


def test_client_system_mode_requires_profile(client_api: TestClient) -> None:
    token = setup_admin(client_api, role="client")
    headers = {"X-CSRF-Token": token}
    response = client_api.post("/api/v1/system/connect", headers=headers)
    assert response.status_code in {400, 422, 502}
    status = client_api.get("/api/v1/system/info")
    assert status.status_code == 200
    assert status.json()["app"]["role"] == "client"
    assert csrf(client_api)
