"""Admin integration tests."""

from __future__ import annotations

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_admin_pages(admin_client, proxy_user, vless_inbound):
    for name in (
        "admin:index",
        "admin:proxy_proxyuser_changelist",
        "admin:proxy_proxyuser_change",
        "admin:proxy_inbound_changelist",
        "admin:certificates_certificate_changelist",
        "admin:operations_alert_changelist",
        "admin:operations_auditevent_changelist",
    ):
        kwargs = {"object_id": str(proxy_user.pk)} if name.endswith("_change") else {}
        response = admin_client.get(reverse(name, kwargs=kwargs))
        assert response.status_code == 200, name


@pytest.mark.django_db
def test_subscription_panel_reveal_and_rotate(admin_client, proxy_user, vless_inbound):
    url = reverse("admin:proxy_proxyuser_subscription", args=[proxy_user.pk])
    response = admin_client.get(url)
    assert response.status_code == 200
    assert proxy_user.reveal_subscription_token().encode() not in response.content
    response = admin_client.post(url, {"action": "reveal"})
    assert response.status_code == 200
    assert proxy_user.reveal_subscription_token().encode() in response.content
    old = proxy_user.reveal_subscription_token()
    response = admin_client.post(url, {"action": "rotate"})
    assert response.status_code == 302
    proxy_user.refresh_from_db()
    assert proxy_user.reveal_subscription_token() != old


@pytest.mark.django_db
def test_admin_actions(admin_client, proxy_user):
    url = reverse("admin:proxy_proxyuser_changelist")
    response = admin_client.post(
        url,
        {"action": "disable_users", "_selected_action": [str(proxy_user.pk)]},
        follow=True,
    )
    assert response.status_code == 200
    proxy_user.refresh_from_db()
    assert proxy_user.enabled is False


@pytest.mark.django_db
def test_certificate_import_view(admin_client, certificate):
    admin_url = reverse("admin:certificates_certificate_import")
    response = admin_client.get(admin_url, follow=True)
    assert response.status_code == 200
    assert "导入证书" in response.content.decode()
    payload = {
        "domain": certificate.domain,
        "certificate": certificate.cert_file.read_text(),
        "private_key": certificate.key_file.read_text(),
    }
    response = admin_client.post(reverse("console:certificate_import"), payload)
    assert response.status_code == 302
    from ostium.certificates.models import Certificate

    assert Certificate.objects.filter(domain=certificate.domain).exists()
