"""Authentication edge cases and security middleware."""

from __future__ import annotations

import pytest
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice


def token_for(device):
    value = totp(device.bin_key, device.step, device.t0, device.digits, device.drift)
    return f"{value:0{device.digits}d}"


@pytest.mark.django_db
def test_otp_without_pending_session(client):
    response = client.get(reverse("accounts:otp"))
    assert response.status_code == 302
    assert response.url == reverse("accounts:login")


@pytest.mark.django_db
def test_otp_recovery_page(client, admin_user):
    client.force_login(admin_user)
    response = client.get(reverse("accounts:totp_recovery"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_totp_disable_wrong_password(client, admin_user):
    device = TOTPDevice.objects.create(user=admin_user, name="default", confirmed=True)
    client.force_login(admin_user)
    session = client.session
    session["otp_device_id"] = device.persistent_id
    session.save()
    response = client.post(
        reverse("accounts:totp_disable"),
        {"password": "wrong", "token": token_for(device)},
    )
    assert response.status_code == 200
    response = client.post(
        reverse("accounts:totp_disable"),
        {"password": "Ostium-Test-Password-2026", "token": "000000"},
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_totp_disable_success(client, admin_user):
    device = TOTPDevice.objects.create(user=admin_user, name="default", confirmed=True)
    client.force_login(admin_user)
    session = client.session
    session["otp_device_id"] = device.persistent_id
    session.save()
    response = client.post(
        reverse("accounts:totp_disable"),
        {"password": "Ostium-Test-Password-2026", "token": token_for(device)},
    )
    assert response.status_code == 302
    assert not TOTPDevice.objects.filter(user=admin_user).exists()


@pytest.mark.django_db
def test_totp_setup_already_verified(client, admin_user):
    device = TOTPDevice.objects.create(user=admin_user, name="default", confirmed=True)
    client.force_login(admin_user)
    session = client.session
    session["otp_device_id"] = device.persistent_id
    session.save()
    response = client.get(reverse("accounts:totp_setup"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_password_change_validation(client, admin_user):
    client.force_login(admin_user)
    response = client.post(
        reverse("accounts:password_change"),
        {
            "old_password": "wrong",
            "new_password1": "Another-Strong-Password-2026",
            "new_password2": "Another-Strong-Password-2026",
        },
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_login_redirects_authenticated(client, admin_user):
    client.force_login(admin_user)
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 302


@pytest.mark.django_db
def test_middleware_requires_totp_verification(client, admin_user):
    TOTPDevice.objects.create(user=admin_user, name="default", confirmed=True)
    client.force_login(admin_user)
    response = client.get(reverse("console:dashboard"))
    assert response.status_code == 302
    assert response.url == reverse("accounts:otp")


@pytest.mark.django_db
def test_middleware_requires_setup_when_public(client, admin_user, settings):
    settings.OSTIUM_REQUIRE_TOTP = True
    client.force_login(admin_user)
    response = client.get(reverse("console:dashboard"))
    assert response.status_code == 302
    assert response.url == reverse("accounts:totp_setup")


@pytest.mark.django_db
def test_public_exempt_paths(client, admin_user, settings):
    settings.OSTIUM_REQUIRE_TOTP = True
    client.force_login(admin_user)
    assert client.get("/healthz").status_code == 200
