"""Authentication, TOTP and password-change tests."""

from __future__ import annotations

import pytest
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice


def token_for(device: TOTPDevice) -> str:
    value = totp(device.bin_key, device.step, device.t0, device.digits, device.drift)
    return f"{value:0{device.digits}d}"


@pytest.mark.django_db
def test_login_page(client):
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 200
    assert b"Ostium" in response.content


@pytest.mark.django_db
def test_login_success(client, admin_user):
    response = client.post(
        reverse("accounts:login"),
        {"username": "admin", "password": "Ostium-Test-Password-2026"},
    )
    assert response.status_code == 302
    assert response.url == reverse("console:dashboard")


@pytest.mark.django_db
def test_login_failure(client, admin_user):
    response = client.post(reverse("accounts:login"), {"username": "admin", "password": "wrong"})
    assert response.status_code == 200
    assert b"incorrect" in response.content.lower()


@pytest.mark.django_db
def test_totp_is_required_after_password(client, admin_user):
    device = TOTPDevice.objects.create(user=admin_user, name="default", confirmed=True)
    response = client.post(
        reverse("accounts:login"),
        {"username": "admin", "password": "Ostium-Test-Password-2026"},
    )
    assert response.status_code == 302
    assert response.url == reverse("accounts:otp")
    response = client.post(reverse("accounts:otp"), {"token": token_for(device)})
    assert response.status_code == 302
    assert client.session["otp_device_id"]


@pytest.mark.django_db
def test_totp_rejects_bad_code(client, admin_user):
    TOTPDevice.objects.create(user=admin_user, name="default", confirmed=True)
    client.post(reverse("accounts:login"), {"username": "admin", "password": "Ostium-Test-Password-2026"})
    response = client.post(reverse("accounts:otp"), {"token": "000000"})
    assert response.status_code == 200
    assert b"not valid" in response.content.lower()


@pytest.mark.django_db
def test_totp_setup_enables_device(client, admin_user):
    client.force_login(admin_user)
    response = client.get(reverse("accounts:totp_setup"))
    assert response.status_code == 200
    device = TOTPDevice.objects.get(user=admin_user, confirmed=False)
    response = client.post(reverse("accounts:totp_setup"), {"token": token_for(device)})
    assert response.status_code == 200
    device.refresh_from_db()
    assert device.confirmed is True


@pytest.mark.django_db
def test_force_password_change(client, admin_user):
    profile = admin_user.ostium_profile
    profile.must_change_password = True
    profile.save()
    client.force_login(admin_user)
    response = client.get(reverse("console:dashboard"))
    assert response.status_code == 302
    assert response.url == reverse("accounts:password_change")
    response = client.post(
        reverse("accounts:password_change"),
        {
            "old_password": "Ostium-Test-Password-2026",
            "new_password1": "Another-Strong-Password-2026",
            "new_password2": "Another-Strong-Password-2026",
        },
    )
    assert response.status_code == 302
    profile.refresh_from_db()
    assert profile.must_change_password is False


@pytest.mark.django_db
def test_logout(client, admin_user):
    client.force_login(admin_user)
    response = client.post(reverse("accounts:logout"))
    assert response.status_code == 302
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_anonymous_console_redirects(client):
    response = client.get(reverse("console:dashboard"))
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.django_db
def test_axes_locks_after_failures(client, admin_user, settings):
    settings.AXES_ENABLED = True
    for _ in range(5):
        client.post(reverse("accounts:login"), {"username": "admin", "password": "wrong"})
    response = client.post(
        reverse("accounts:login"),
        {"username": "admin", "password": "Ostium-Test-Password-2026"},
    )
    assert response.status_code in {403, 429}
