"""More console action coverage."""

from __future__ import annotations

import pytest
from django.utils import timezone
from django_q.models import Task

from ostium.proxy.models import ProxyUser


@pytest.mark.django_db
def test_user_detail_actions(admin_client, proxy_user, vless_inbound):
    url = f"/users/{proxy_user.pk}/"
    response = admin_client.post(url, {"action": "rotate_credentials"})
    assert response.status_code == 200
    response = admin_client.post(url, {"action": "rotate_subscription"})
    assert response.status_code == 200
    response = admin_client.post(url, {"action": "reset_usage"})
    assert response.status_code == 200
    response = admin_client.post(url, {"action": "unknown"})
    assert response.status_code == 400
    other = ProxyUser.objects.create(name="delete-me")
    response = admin_client.post(f"/users/{other.pk}/", {"action": "delete"})
    assert response.status_code == 302
    assert not ProxyUser.objects.filter(pk=other.pk).exists()


@pytest.mark.django_db
def test_inbound_rotate(admin_client, inbounds):
    response = admin_client.post(
        "/inbounds/",
        {"kind": "vless", "action": "rotate_keys", "vless-enabled": "on", "vless-port": "443"},
    )
    assert response.status_code == 302


@pytest.mark.django_db
def test_connections_close(admin_client, monkeypatch):
    import ostium.operations.console_views as views

    calls = []

    class FakeClient:
        def close_all(self):
            calls.append("all")

        def close_connection(self, connection_id):
            calls.append(connection_id)

    monkeypatch.setattr(views, "ClashClient", lambda: FakeClient())
    assert admin_client.post("/connections/", {"action": "close_all"}).status_code == 302
    assert admin_client.post("/connections/", {"action": "close", "connection_id": "abc"}).status_code == 302
    assert calls == ["all", "abc"]


@pytest.mark.django_db
def test_certificate_refresh(admin_client, certificate):
    response = admin_client.post("/certificates/", {"certificate_id": certificate.pk})
    assert response.status_code == 302


@pytest.mark.django_db
def test_jobs_cancel(admin_client):
    task = Task.objects.create(
        id="task-1",
        name="test",
        func="ostium.test",
        started=timezone.now(),
        stopped=timezone.now(),
        success=True,
    )
    response = admin_client.post("/jobs/", {"action": "cancel", "task_id": task.id})
    assert response.status_code == 302
    from django_q.models import OrmQ
    from django_q.signing import SignedPackage

    queued = OrmQ.objects.create(
        key="ostium",
        payload=SignedPackage.dumps(
            {"id": "queued-1", "name": "queued", "func": "ostium.test", "args": (), "kwargs": {}}
        ),
    )
    response = admin_client.post("/jobs/", {"action": "cancel", "task_id": "queued-1"})
    assert response.status_code == 302
    assert not OrmQ.objects.filter(pk=queued.pk).exists()
    response = admin_client.post("/jobs/", {"action": "cancel", "task_id": "missing"})
    assert response.status_code == 302


@pytest.mark.django_db
def test_system_restart_and_diagnostics(admin_client):
    assert admin_client.post("/system/", {"action": "restart_core"}).status_code == 302
    response = admin_client.get("/system/?download=diagnostics")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/gzip"
    assert response.content[:2] == b"\x1f\x8b"


@pytest.mark.django_db
def test_settings_invalid(admin_client):
    response = admin_client.post("/settings/", {"server_dns_mode": "nope"})
    assert response.status_code == 200
    from constance import config

    assert config.server_dns_mode in {"auto", "doh", "udp"}


@pytest.mark.django_db
def test_logs_download(admin_client, settings, tmp_path):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "sing-box.log").write_text("INFO hello\nERROR boom\n")
    response = admin_client.get("/logs/?source=sing-box&download=1")
    assert response.status_code == 200
    assert response["Content-Disposition"].endswith('"sing-box.log"')
    response = admin_client.get("/logs/?source=sing-box&q=boom")
    assert b"boom" in response.content


@pytest.mark.django_db
def test_subscriptions_with_user(admin_client, proxy_user, vless_inbound):
    response = admin_client.get("/subscriptions/", {"q": "alice"})
    assert response.status_code == 200
    assert b"alice" in response.content


@pytest.mark.django_db
def test_dashboard_with_usage(admin_client, proxy_user, settings, tmp_path):
    from ostium.engine.runtime import write_usage

    settings.OSTIUM_DATA_DIR = str(tmp_path)
    proxy_user.last_seen_at = timezone.now()
    proxy_user.save(update_fields=["last_seen_at"])
    write_usage(
        {
            "stats_ok": True,
            "users": {
                "alice": {
                    "uplink_rate": 10,
                    "downlink_rate": 20,
                    "online": True,
                    "last_activity": timezone.now().isoformat(),
                }
            },
        }
    )
    response = admin_client.get("/")
    assert response.status_code == 200
    assert b"alice" in response.content
