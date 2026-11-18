"""REST API tests."""

from __future__ import annotations

import pytest

from ostium.accounts.models import ApiKey
from ostium.proxy.models import ProxyUser


@pytest.mark.django_db
def test_requires_api_key(client):
    response = client.get("/api/v1/users")
    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 403
    assert body["code"]
    assert body["request_id"]


@pytest.mark.django_db
def test_user_crud(api_client):
    response = api_client.get("/api/v1/users")
    assert response.status_code == 200
    assert response.json()["count"] == 0

    response = api_client.post("/api/v1/users", {"name": "alice", "quota_bytes": 1000}, format="json")
    assert response.status_code == 201
    user_id = response.json()["id"]
    assert response.json()["status"] == "active"

    response = api_client.patch(f"/api/v1/users/{user_id}", {"enabled": False}, format="json")
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    response = api_client.post(f"/api/v1/users/{user_id}/rotate")
    assert response.status_code == 200
    assert response.json()["detail"] == "Credentials rotated."

    response = api_client.post(f"/api/v1/users/{user_id}/reset-usage")
    assert response.status_code == 200

    response = api_client.get(f"/api/v1/users/{user_id}/usage")
    assert response.status_code == 200
    assert "daily" in response.json()

    response = api_client.delete(f"/api/v1/users/{user_id}")
    assert response.status_code == 204
    assert not ProxyUser.objects.filter(pk=user_id).exists()


@pytest.mark.django_db
def test_subscription_endpoints(api_client, proxy_user, vless_inbound):
    response = api_client.get(f"/api/v1/users/{proxy_user.pk}/subscription")
    assert response.status_code == 200
    payload = response.json()
    assert payload["revealed"] is False
    assert "…" in payload["token"]
    assert "links" not in payload

    response = api_client.post(f"/api/v1/users/{proxy_user.pk}/subscription/reveal")
    assert response.status_code == 200
    payload = response.json()
    assert payload["revealed"] is True
    assert len(payload["links"]) == 4

    old = proxy_user.reveal_subscription_token()
    response = api_client.post(f"/api/v1/users/{proxy_user.pk}/subscription/rotate")
    assert response.status_code == 200
    proxy_user.refresh_from_db()
    assert proxy_user.reveal_subscription_token() != old


@pytest.mark.django_db
def test_read_only_key_cannot_write(db, admin_user, proxy_user):
    from rest_framework.test import APIClient

    _key, plaintext = ApiKey.objects.create_key(name="readonly", scope=ApiKey.Scope.READ, created_by=admin_user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {plaintext}")
    assert client.get("/api/v1/users").status_code == 200
    response = client.post("/api/v1/users", {"name": "nope"}, format="json")
    assert response.status_code == 403
    assert "read-only" in response.content.decode().lower()


@pytest.mark.django_db
def test_inbounds(api_client, vless_inbound):
    response = api_client.get("/api/v1/inbounds")
    assert response.status_code == 200
    assert len(response.json()) >= 1
    response = api_client.get("/api/v1/inbounds/vless")
    assert response.status_code == 200
    assert response.json()["kind"] == "vless"
    response = api_client.patch("/api/v1/inbounds/vless", {"port": 8443}, format="json")
    assert response.status_code == 200
    vless_inbound.refresh_from_db()
    assert vless_inbound.port == 8443
    response = api_client.post("/api/v1/inbounds/vless/reality-keys")
    assert response.status_code == 200
    assert "public_key" in response.json()


@pytest.mark.django_db
def test_certificates(api_client, certificate, inbounds):
    response = api_client.get("/api/v1/certificates")
    assert response.status_code == 200
    assert response.json()[0]["domain"] == "vpn.example.com"
    response = api_client.post(
        f"/api/v1/certificates/{certificate.pk}/assign",
        {"inbounds": ["hysteria2"]},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["assigned"] == ["hysteria2"]


@pytest.mark.django_db
def test_stats_and_settings(api_client):
    response = api_client.get("/api/v1/stats/overview")
    assert response.status_code == 200
    assert "runtime" in response.json()
    response = api_client.get("/api/v1/stats/traffic?days=7")
    assert response.status_code == 200
    assert response.json()["days"] == 7

    response = api_client.patch("/api/v1/settings", {"server_name": "API Ostium"}, format="json")
    assert response.status_code == 200
    assert response.json()["updated"] == ["server_name"]
    response = api_client.get("/api/v1/settings")
    assert response.json()["server_name"] == "API Ostium"


@pytest.mark.django_db
def test_validation_error_shape(api_client):
    response = api_client.post("/api/v1/users", {"name": ""}, format="json")
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["status"] == 400


def test_schema(client):
    response = client.get("/api/schema")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/vnd.oai.openapi")


@pytest.mark.django_db
def test_alerts_and_audit(api_client, admin_user):
    from ostium.operations.models import Alert, AuditEvent

    alert = Alert.objects.create(code="test", fingerprint="test", message="Test alert")
    response = api_client.get("/api/v1/alerts")
    assert response.status_code == 200
    response = api_client.post(f"/api/v1/alerts/{alert.pk}/ack")
    assert response.status_code == 200
    alert.refresh_from_db()
    assert alert.acknowledged_at is not None

    AuditEvent.objects.create(actor=admin_user, action="test.event", target="x")
    response = api_client.get("/api/v1/audit")
    assert response.status_code == 200
    assert response.json()["count"] >= 1


@pytest.mark.django_db
def test_backup_api(api_client, admin_user, settings):
    from ostium.operations.models import AuditEvent, Backup

    response = api_client.post("/api/v1/backups", {"password": "short"}, format="json")
    assert response.status_code == 400
    response = api_client.post("/api/v1/backups", {"password": "a-long-backup-password"}, format="json")
    assert response.status_code == 201
    assert response.json()["encrypted"] is True
    backup = Backup.objects.get()
    assert backup.created_by == admin_user
    assert AuditEvent.objects.get(action="backup.created").actor == admin_user
