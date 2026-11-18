"""Console page smoke tests."""

from __future__ import annotations

import pytest
from django.urls import reverse


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name",
    [
        "console:dashboard",
        "console:users",
        "console:subscriptions",
        "console:inbounds",
        "console:connections",
        "console:certificates",
        "console:logs",
        "console:jobs",
        "console:system",
        "console:settings",
        "console:audit",
    ],
)
def test_console_pages_render(admin_client, proxy_user, vless_inbound, name):
    response = admin_client.get(reverse(name))
    assert response.status_code == 200
    assert b"Ostium" in response.content


@pytest.mark.django_db
def test_user_detail_and_actions(admin_client, proxy_user, vless_inbound):
    url = reverse("console:user_detail", args=[proxy_user.pk])
    assert admin_client.get(url).status_code == 200
    response = admin_client.post(url, {"action": "reveal"})
    assert response.status_code == 200
    assert proxy_user.reveal_subscription_token().encode() in response.content
    response = admin_client.post(
        url,
        {
            "action": "save",
            "name": proxy_user.name,
            "quota": "50G",
            "quota_cycle": "monthly",
            "note": "updated",
            "enabled": "on",
        },
    )
    assert response.status_code == 302
    proxy_user.refresh_from_db()
    assert proxy_user.quota_bytes == 50 * 1024**3
    assert proxy_user.note == "updated"


@pytest.mark.django_db
def test_logs_filter(admin_client):
    response = admin_client.get(reverse("console:logs"), {"source": "ostium", "q": "nothing"})
    assert response.status_code == 200
    response = admin_client.get(reverse("console:logs"), {"source": "invalid"})
    assert response.status_code == 404


@pytest.mark.django_db
def test_settings_save(admin_client):
    response = admin_client.post(
        reverse("console:settings"),
        {
            "server_name": "My Ostium",
            "public_host": "vpn.example.com",
            "public_base_url": "https://vpn.example.com",
            "subscription_update_interval": "12",
            "server_dns_mode": "auto",
            "server_dns_doh_url": "https://1.1.1.1/dns-query",
            "block_private_egress": "on",
            "log_level": "info",
            "webhook_url": "",
            "webhook_secret": "",
            "traffic_retention_days": "90",
            "audit_retention_days": "365",
            "auto_backup_keep": "7",
        },
    )
    assert response.status_code == 302
    from constance import config

    assert config.server_name == "My Ostium"
