from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from ostium.engine.manager import EngineError
from tests.conftest import setup_admin


def _headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


VLESS = (
    "vless://2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e@vpn.example.com:443"
    "?encryption=none&security=reality&sni=www.apple.com&fp=chrome"
    "&pbk=Bs2KLXAKuw5pGFpBIwnyt896Y8mhNJHewMHHY0en6hM&sid=55e1651e#HK"
)


def test_rules_crud_reorder_and_test(api_client: TestClient, session_token: str) -> None:
    headers = _headers(session_token)
    first = api_client.post(
        "/api/v1/rules",
        json={
            "action": "direct",
            "match": {"domain_suffix": [".cn"], "domain_keyword": ["baidu"]},
            "note": "cn",
            "priority": 10,
        },
        headers=headers,
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["rule"]["id"]
    assert first.json()["applied"] is False
    assert "subscriptions" in first.json()["warning"]

    second = api_client.post(
        "/api/v1/rules",
        json={"action": "block", "match": {"ip_cidr": ["10.0.0.0/8"]}, "priority": 20},
        headers=headers,
    )
    third = api_client.post(
        "/api/v1/rules",
        json={"action": "proxy", "match": {"port": [443], "network": ["tcp"]}},
        headers=headers,
    )
    assert second.status_code == third.status_code == 201

    listing = api_client.get("/api/v1/rules").json()["rules"]
    assert listing[0]["id"] == first_id

    match = api_client.post(
        "/api/v1/rules/test",
        json={"domain": "www.baidu.cn", "ip": "10.1.2.3", "port": 443, "network": "tcp"},
        headers=headers,
    )
    assert match.status_code == 200
    assert match.json()["matched"] is True
    assert match.json()["rule"]["action"] == "direct"

    no_match = api_client.post(
        "/api/v1/rules/test",
        json={"domain": "example.com", "process_name": "curl"},
        headers=headers,
    )
    assert no_match.json() == {"matched": False, "action": "proxy"}

    patched = api_client.patch(
        f"/api/v1/rules/{first_id}",
        json={"action": "block", "enabled": False, "note": "off", "priority": 1},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["rule"]["enabled"] is False

    assert api_client.patch("/api/v1/rules/missing", json={}, headers=headers).status_code == 404
    assert api_client.delete("/api/v1/rules/missing", headers=headers).status_code == 404

    reordered = api_client.post(
        "/api/v1/rules/reorder",
        json={"ids": [second.json()["rule"]["id"], "missing", first_id]},
        headers=headers,
    )
    assert reordered.status_code == 200

    assert api_client.delete(f"/api/v1/rules/{first_id}", headers=headers).status_code == 200


def test_rule_sets_lifecycle(api_client: TestClient, session_token: str, settings) -> None:
    headers = _headers(session_token)
    assert api_client.get("/api/v1/rule-sets").json() == {"rule_sets": []}

    created = api_client.post(
        "/api/v1/rule-sets",
        json={"name": "ads", "url": "https://rules.example.com/ads.srs"},
        headers=headers,
    )
    assert created.status_code == 201
    rule_set = created.json()["rule_set"]
    assert rule_set["format"] == "binary"

    duplicate = api_client.post(
        "/api/v1/rule-sets",
        json={"name": "ads", "url": "https://rules.example.com/other.srs"},
        headers=headers,
    )
    assert duplicate.status_code == 409

    with respx.mock:
        respx.get("https://rules.example.com/ads.srs").mock(
            return_value=httpx.Response(200, content=b"rules", headers={"etag": '"v1"'})
        )
        updated = api_client.post(f"/api/v1/rule-sets/{rule_set['id']}/update", headers=headers)
    assert updated.status_code == 200
    assert updated.json()["result"]["updated"] is True
    assert updated.json()["rule_set"]["sha256"]

    with respx.mock:
        respx.get("https://rules.example.com/ads.srs").mock(return_value=httpx.Response(304))
        not_modified = api_client.post(
            f"/api/v1/rule-sets/{rule_set['id']}/update", headers=headers
        )
    assert not_modified.json()["result"]["reason"] == "not_modified"

    with respx.mock:
        respx.get("https://rules.example.com/ads.srs").mock(
            return_value=httpx.Response(500, text="down")
        )
        failure = api_client.post(f"/api/v1/rule-sets/{rule_set['id']}/update", headers=headers)
    assert failure.status_code == 200
    assert failure.json()["result"]["updated"] is False
    assert failure.json()["rule_set"]["last_error"]

    assert api_client.post("/api/v1/rule-sets/missing/update", headers=headers).status_code == 404
    assert api_client.delete("/api/v1/rule-sets/missing", headers=headers).status_code == 404
    assert (
        api_client.delete(f"/api/v1/rule-sets/{rule_set['id']}", headers=headers).status_code == 200
    )


def test_client_profiles_crud_import_refresh_errors(client_api: TestClient) -> None:
    token = setup_admin(client_api, role="client")
    headers = _headers(token)

    async def no_profile(session: object) -> dict:
        raise EngineError("no profile", "no_profile", 400)

    client_api.app.state.services.engine.apply_client = no_profile  # type: ignore[method-assign]
    assert client_api.get("/api/v1/profiles").json() == {"profiles": []}

    bad = client_api.post("/api/v1/profiles", json={"name": "bad"}, headers=headers)
    assert bad.status_code == 400
    assert bad.json()["code"] == "bad_request"

    invalid = client_api.post(
        "/api/v1/profiles", json={"name": "bad", "text": "vmess://x"}, headers=headers
    )
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "profile_error"

    with respx.mock:
        respx.get("https://sub.example.com/hk").mock(return_value=httpx.Response(200, text=VLESS))
        created = client_api.post(
            "/api/v1/profiles",
            json={"name": "HK", "url": "https://sub.example.com/hk"},
            headers=headers,
        )
    assert created.status_code == 201, created.text
    profile = created.json()["profile"]
    assert profile["kind"] == "subscription"
    assert created.json()["applied"] is False
    assert created.json()["warning"]

    with respx.mock:
        respx.get("https://sub.example.com/bad").mock(return_value=httpx.Response(502, text="bad"))
        failed_download = client_api.post(
            "/api/v1/profiles",
            json={"name": "bad", "url": "https://sub.example.com/bad"},
            headers=headers,
        )
    assert failed_download.status_code == 502
    assert failed_download.json()["code"] == "refresh_failed"

    imported = client_api.post(
        "/api/v1/profiles/import", json={"name": "Imported", "text": VLESS}, headers=headers
    )
    assert imported.status_code == 200

    listed = client_api.get("/api/v1/profiles").json()["profiles"]
    assert len(listed) == 2

    patched = client_api.patch(
        f"/api/v1/profiles/{profile['id']}",
        json={
            "name": "HK2",
            "enabled": False,
            "selected_endpoint": profile["endpoints"][0]["tag"],
            "sort_order": 5,
        },
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["profile"]["name"] == "HK2"
    assert patched.json()["profile"]["enabled"] is False

    assert client_api.patch("/api/v1/profiles/missing", json={}, headers=headers).status_code == 404
    assert client_api.delete("/api/v1/profiles/missing", headers=headers).status_code == 404

    with respx.mock:
        respx.get("https://sub.example.com/hk").mock(return_value=httpx.Response(200, text=VLESS))
        refreshed = client_api.post(f"/api/v1/profiles/{profile['id']}/refresh", headers=headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["endpoints"] == 1

    with respx.mock:
        respx.get("https://sub.example.com/hk").mock(return_value=httpx.Response(500, text="no"))
        refresh_failed = client_api.post(
            f"/api/v1/profiles/{profile['id']}/refresh", headers=headers
        )
    assert refresh_failed.status_code == 502
    assert refresh_failed.json()["code"] == "refresh_failed"

    exported = client_api.get(f"/api/v1/profiles/{profile['id']}/export")
    assert exported.status_code == 200
    assert exported.json()["subscription_url"] == "https://sub.example.com/hk"

    tested = client_api.get(f"/api/v1/profiles/{profile['id']}/test")
    assert tested.status_code == 200
    assert tested.json()["results"][0]["error"] == "not loaded in the running core"

    assert (
        client_api.delete(f"/api/v1/profiles/{profile['id']}", headers=headers).status_code == 200
    )


def test_manual_profile_refresh_requires_url(client_api: TestClient) -> None:
    token = setup_admin(client_api, role="client")
    headers = _headers(token)
    created = client_api.post(
        "/api/v1/profiles", json={"name": "manual", "text": VLESS}, headers=headers
    )
    profile_id = created.json()["profile"]["id"]
    response = client_api.post(f"/api/v1/profiles/{profile_id}/refresh", headers=headers)
    assert response.status_code == 400
    assert response.json()["code"] == "profile_error"


def test_client_rules_apply_paths(client_api: TestClient) -> None:
    token = setup_admin(client_api, role="client")
    headers = _headers(token)
    services = client_api.app.state.services

    created = client_api.post(
        "/api/v1/rules",
        json={"action": "proxy", "match": {"domain": ["example.com"]}},
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["applied"] is False

    async def applied(session: object) -> dict:
        return {"status": {"revision": "r1"}}

    services.engine.apply_client = applied  # type: ignore[method-assign]
    enabled = client_api.patch(
        f"/api/v1/rules/{created.json()['rule']['id']}",
        json={"note": "updated"},
        headers=headers,
    )
    assert enabled.status_code == 200
    assert enabled.json()["applied"] is True

    async def fatal(session: object) -> dict:
        raise EngineError("bad", "engine_check_failed", 422)

    services.engine.apply_client = fatal  # type: ignore[method-assign]
    failed = client_api.post(
        "/api/v1/rules",
        json={"action": "direct", "match": {"port": [80]}},
        headers=headers,
    )
    assert failed.status_code == 422
    assert failed.json()["code"] == "engine_check_failed"


def test_profile_patch_sort_order_and_proxy_history(client_api: TestClient) -> None:
    token = setup_admin(client_api, role="client")
    headers = _headers(token)
    services = client_api.app.state.services

    async def no_profile(session: object) -> dict:
        raise EngineError("no profile", "no_profile", 400)

    services.engine.apply_client = no_profile  # type: ignore[method-assign]
    created = client_api.post(
        "/api/v1/profiles", json={"name": "HK", "text": VLESS}, headers=headers
    )
    profile = created.json()["profile"]
    patched = client_api.patch(
        f"/api/v1/profiles/{profile['id']}", json={"sort_order": 3}, headers=headers
    )
    assert patched.status_code == 200
    assert patched.json()["profile"]["sort_order"] == 3

    async def proxies() -> dict:
        return {
            "proxies": {
                profile["endpoints"][0]["tag"]: {"history": []},
            }
        }

    services.clash.proxies = proxies  # type: ignore[method-assign]
    tested = client_api.get(f"/api/v1/profiles/{profile['id']}/test")
    assert tested.status_code == 200
    assert tested.json()["results"][0]["delay_ms"] is None


def test_client_profile_engine_failures(client_api: TestClient) -> None:
    token = setup_admin(client_api, role="client")
    headers = _headers(token)

    async def no_profile(session: object) -> dict:
        raise EngineError("no profile", "no_profile", 400)

    client_api.app.state.services.engine.apply_client = no_profile  # type: ignore[method-assign]
    created = client_api.post(
        "/api/v1/profiles", json={"name": "manual", "text": VLESS}, headers=headers
    )
    assert created.status_code == 201
    assert created.json()["applied"] is False

    async def fatal(session: object) -> dict:
        raise EngineError("bad config", "engine_check_failed", 422)

    client_api.app.state.services.engine.apply_client = fatal  # type: ignore[method-assign]
    failed = client_api.post(
        "/api/v1/profiles", json={"name": "other", "text": VLESS}, headers=headers
    )
    assert failed.status_code == 422
    assert failed.json()["code"] == "engine_check_failed"
