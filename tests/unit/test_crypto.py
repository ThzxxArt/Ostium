"""Field encryption tests."""

from __future__ import annotations

import base64

import pytest
from django.core.exceptions import ImproperlyConfigured

from ostium.accounts.crypto import decrypt_text, encrypt_text
from ostium.proxy.models import ProxyUser


@pytest.mark.django_db
def test_round_trip(proxy_user):
    payload = encrypt_text(proxy_user, "password_enc", "s3cret")
    assert payload.startswith("v1:")
    assert payload != "s3cret"
    assert decrypt_text(proxy_user, "password_enc", payload) == "s3cret"


@pytest.mark.django_db
def test_aad_binds_field(proxy_user):
    payload = encrypt_text(proxy_user, "password_enc", "s3cret")
    with pytest.raises(Exception):
        decrypt_text(proxy_user, "ss_password_enc", payload)


@pytest.mark.django_db
def test_aad_binds_primary_key(proxy_user):
    other, _ = __import__("ostium.proxy.services", fromlist=["create_proxy_user"]).create_proxy_user("bob")
    payload = encrypt_text(proxy_user, "password_enc", "s3cret")
    with pytest.raises(Exception):
        decrypt_text(other, "password_enc", payload)


@pytest.mark.django_db
def test_unsaved_instance_rejected():
    user = ProxyUser(name="unsaved")
    user.pk = None
    with pytest.raises(ValueError):
        encrypt_text(user, "password_enc", "value")


def test_invalid_key_length(settings, monkeypatch):
    settings.OSTIUM_FIELD_KEY = base64.b64encode(b"short").decode()
    with pytest.raises(ImproperlyConfigured):
        from ostium.accounts.crypto import _key

        _key()
