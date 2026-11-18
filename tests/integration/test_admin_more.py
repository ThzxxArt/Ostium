"""Admin action and display coverage."""

from __future__ import annotations

import pytest
from django.urls import reverse

from ostium.operations.models import Alert
from ostium.proxy.models import Inbound, TrafficDaily


@pytest.mark.django_db
def test_proxy_user_actions(admin_client, proxy_user):
    url = reverse("admin:proxy_proxyuser_changelist")
    actions = (
        "enable_users",
        "disable_users",
        "rotate_subscriptions",
        "rotate_credentials",
        "reset_usage",
    )
    for action in actions:
        response = admin_client.post(
            url,
            {"action": action, "_selected_action": [str(proxy_user.pk)]},
            follow=True,
        )
        assert response.status_code == 200


@pytest.mark.django_db
def test_inbound_admin_change(admin_client, inbounds, certificate):
    inbound = Inbound.objects.get(kind="hysteria2")
    url = reverse("admin:proxy_inbound_change", args=[inbound.pk])
    response = admin_client.get(url)
    assert response.status_code == 200
    response = admin_client.post(
        url,
        {
            "kind": "hysteria2",
            "enabled": "on",
            "listen": "0.0.0.0",
            "port": "9443",
            "certificate": str(certificate.pk),
        },
    )
    assert response.status_code == 302
    inbound.refresh_from_db()
    assert inbound.port == 9443


@pytest.mark.django_db
def test_proxy_admin_lists(admin_client, proxy_user, inbounds):
    TrafficDaily.objects.create(user=proxy_user, uplink=1, downlink=2)
    for name in (
        "admin:proxy_inbound_changelist",
        "admin:proxy_trafficdaily_changelist",
        "admin:proxy_statsepoch_changelist",
    ):
        assert admin_client.get(reverse(name)).status_code == 200


@pytest.mark.django_db
def test_certificate_admin_branches(admin_client, certificate, inbounds):
    url = reverse("admin:certificates_certificate_import")
    response = admin_client.post(url, {"domain": "vpn.example.com", "certificate": "bad", "private_key": "bad"})
    assert response.status_code == 200
    assert b"error" in response.content.lower() or b"invalid" in response.content.lower()
    changelist = reverse("admin:certificates_certificate_changelist")
    response = admin_client.post(
        changelist,
        {"action": "refresh_certificates", "_selected_action": [str(certificate.pk)]},
        follow=True,
    )
    assert response.status_code == 200
    change = reverse("admin:certificates_certificate_change", args=[certificate.pk])
    assert admin_client.get(change).status_code == 200


@pytest.mark.django_db
def test_operations_admin(admin_client):
    alert = Alert.objects.create(code="x", fingerprint="x", message="x", level="critical")
    url = reverse("admin:operations_alert_changelist")
    response = admin_client.post(
        url,
        {"action": "acknowledge", "_selected_action": [str(alert.pk)]},
        follow=True,
    )
    assert response.status_code == 200
    alert.refresh_from_db()
    assert alert.acknowledged_at is not None
    assert admin_client.get(reverse("admin:operations_runtimestate_changelist")).status_code == 200


@pytest.mark.django_db
def test_subscription_panel_sections(admin_client, proxy_user):
    url = reverse("admin:proxy_proxyuser_subscription", args=[proxy_user.pk])
    response = admin_client.get(url)
    assert response.status_code == 200
    assert b"Subscription-Userinfo" in response.content


@pytest.mark.django_db
def test_user_admin_actions_without_users(admin_client):
    response = admin_client.post(
        reverse("admin:proxy_proxyuser_changelist"),
        {"action": "rotate_subscriptions", "_selected_action": []},
        follow=True,
    )
    assert response.status_code == 200
