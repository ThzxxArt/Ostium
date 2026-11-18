"""Additional API success/error branches."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from django_q.models import Task

from ostium.accounts.models import ApiKey


@pytest.mark.django_db
def test_jobs_and_cancel(api_client):
    task = Task.objects.create(
        id="job-1",
        name="job",
        func="ostium.func",
        started=timezone.now(),
        stopped=timezone.now(),
        success=True,
    )
    response = api_client.get("/api/v1/jobs")
    assert response.json()["count"] == 1
    response = api_client.get(f"/api/v1/jobs/{task.id}")
    assert response.status_code == 200
    response = api_client.post(f"/api/v1/jobs/{task.id}/cancel")
    assert response.status_code == 409


@pytest.mark.django_db
def test_certificate_import_and_delete(api_client, certificate, inbounds):
    payload = {
        "domain": certificate.domain,
        "certificate": certificate.cert_file.read_text(),
        "private_key": certificate.key_file.read_text(),
        "auto_renew": False,
    }
    response = api_client.post("/api/v1/certificates", payload, format="json")
    assert response.status_code == 201
    cert_id = response.json()["id"]
    response = api_client.delete(f"/api/v1/certificates/{cert_id}")
    assert response.status_code == 204


@pytest.mark.django_db
def test_certificate_assign_invalid(api_client, certificate):
    response = api_client.post(f"/api/v1/certificates/{certificate.pk}/assign", {"inbounds": []}, format="json")
    assert response.status_code == 400
    response = api_client.post(
        f"/api/v1/certificates/{certificate.pk}/assign",
        {"inbounds": ["vless"]},
        format="json",
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_reality_keys_only_vless(api_client, inbounds):
    response = api_client.post("/api/v1/inbounds/trojan/reality-keys")
    assert response.status_code == 400


@pytest.mark.django_db
def test_connections_success(api_client, monkeypatch):
    import ostium.api.views as views

    class Fake:
        def connections(self):
            return [{"id": "1"}]

        def close_all(self):
            return None

        def close_connection(self, connection_id):
            return None

    monkeypatch.setattr(views, "ClashClient", Fake)
    assert api_client.get("/api/v1/connections").json()["connections"] == [{"id": "1"}]
    assert api_client.delete("/api/v1/connections").status_code == 204
    assert api_client.delete("/api/v1/connections/1").status_code == 204


@pytest.mark.django_db
def test_expired_api_key(db, admin_user):
    from rest_framework.test import APIClient

    _key, plaintext = ApiKey.objects.create_key(
        name="expired",
        scope=ApiKey.Scope.READ,
        expiry_date=timezone.now() - timedelta(days=1),
        created_by=admin_user,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {plaintext}")
    assert client.get("/api/v1/users").status_code == 403


@pytest.mark.django_db
def test_backup_read_and_delete(api_client):
    response = api_client.post("/api/v1/backups", {"password": "a-long-backup-password"}, format="json")
    backup_id = response.json()["id"]
    assert api_client.get("/api/v1/backups").json()["count"] == 1
    assert api_client.get(f"/api/v1/backups/{backup_id}").status_code == 200
    assert api_client.delete(f"/api/v1/backups/{backup_id}").status_code == 204


@pytest.mark.django_db
def test_docs_requires_staff(admin_client):
    from django.test import Client

    assert Client().get("/api/docs").status_code in {301, 302}
    assert admin_client.get("/api/docs").status_code == 200
