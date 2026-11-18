"""Extra API and console branches."""

from __future__ import annotations

import pytest


@pytest.mark.django_db
def test_jobs_endpoint(api_client):
    response = api_client.get("/api/v1/jobs")
    assert response.status_code == 200
    assert "results" in response.json()


@pytest.mark.django_db
def test_connections_unavailable(api_client, monkeypatch):
    import ostium.api.views as views
    from ostium.engine.clash import ClashError

    class Broken:
        def __init__(self, *args, **kwargs):
            pass

        def connections(self):
            raise ClashError("down")

        def close_all(self):
            raise ClashError("down")

        def close_connection(self, connection_id):
            raise ClashError("down")

    monkeypatch.setattr(views, "ClashClient", Broken)
    response = api_client.get("/api/v1/connections")
    assert response.status_code == 503
    assert response.json()["connections"] == []
    response = api_client.delete("/api/v1/connections")
    assert response.status_code == 503
    response = api_client.delete("/api/v1/connections/abc")
    assert response.status_code == 503


@pytest.mark.django_db
def test_backup_restore_validation(api_client, proxy_user):
    response = api_client.post("/api/v1/backups", {"password": "a-long-backup-password"}, format="json")
    assert response.status_code == 201
    backup_id = response.json()["id"]
    response = api_client.post(f"/api/v1/backups/{backup_id}/restore", {"password": "wrong-password"}, format="json")
    assert response.status_code == 400
    response = api_client.delete(f"/api/v1/backups/{backup_id}")
    assert response.status_code == 204


@pytest.mark.django_db
def test_audit_filters(api_client, admin_user):
    from ostium.operations.models import AuditEvent

    AuditEvent.objects.create(actor=admin_user, action="user.created", target="a")
    AuditEvent.objects.create(actor=admin_user, action="backup.created", target="b")
    response = api_client.get("/api/v1/audit?action=user")
    assert response.json()["count"] == 1
    response = api_client.get("/api/v1/audit?actor=admin")
    assert response.json()["count"] == 2


@pytest.mark.django_db
def test_settings_validation(api_client):
    response = api_client.patch("/api/v1/settings", {"server_dns_mode": "nope"}, format="json")
    assert response.status_code == 400
    response = api_client.patch("/api/v1/settings", {"server_dns_doh_url": "http://x"}, format="json")
    assert response.status_code == 400
    response = api_client.patch("/api/v1/settings", {"subscription_update_interval": "x"}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_inbound_update_requires_certificate(api_client):
    from ostium.proxy.services import initialize_inbounds

    initialize_inbounds()
    response = api_client.patch(
        "/api/v1/inbounds/hysteria2",
        {"enabled": True},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_console_inbounds_post(admin_client, inbounds):
    response = admin_client.post(
        "/inbounds/",
        {"kind": "vless", "vless-enabled": "on", "vless-listen": "0.0.0.0", "vless-port": "8443"},
    )
    assert response.status_code == 302
    from ostium.proxy.models import Inbound

    assert Inbound.objects.get(kind="vless").port == 8443


@pytest.mark.django_db
def test_console_connections_unavailable(admin_client, monkeypatch):
    import ostium.operations.console_views as views
    from ostium.engine.clash import ClashError

    class Broken:
        def connections(self):
            raise ClashError("down")

    monkeypatch.setattr(views, "ClashClient", lambda: Broken())
    response = admin_client.get("/connections/")
    assert response.status_code == 200
    assert b"down" in response.content


@pytest.mark.django_db
def test_console_system_backup(admin_client, monkeypatch):
    import ostium.operations.console_views as views

    class FakeBackup:
        filename = "backup.ostb"

    monkeypatch.setattr(views, "create_backup", lambda **kwargs: FakeBackup())
    response = admin_client.post(
        "/system/",
        {"action": "backup", "password": "a-long-backup-password", "note": "ui"},
    )
    assert response.status_code == 302


@pytest.mark.django_db
def test_console_audit_filters(admin_client, admin_user):
    from ostium.operations.models import AuditEvent

    AuditEvent.objects.create(actor=admin_user, action="user.created", target="a")
    response = admin_client.get("/audit/", {"action": "user", "actor": "admin"})
    assert response.status_code == 200
    assert b"user.created" in response.content
