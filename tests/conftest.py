"""Shared pytest fixtures."""

from __future__ import annotations

import os
import tempfile

os.environ["OSTIUM_DATA_DIR"] = tempfile.mkdtemp(prefix="ostium-tests-")
os.environ.setdefault("OSTIUM_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault(
    "OSTIUM_FIELD_KEY",
    "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
)

import pytest
from django.contrib.auth import get_user_model

from ostium.certificates.services import generate_self_signed
from ostium.proxy.models import Inbound
from ostium.proxy.services import create_proxy_user, initialize_inbounds


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def admin_user(db):
    User = get_user_model()
    user = User.objects.create_superuser("admin", "admin@example.com", "Ostium-Test-Password-2026")
    profile = user.ostium_profile
    profile.must_change_password = False
    profile.save(update_fields=["must_change_password"])
    return user


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


@pytest.fixture
def proxy_user(db):
    user, _token = create_proxy_user("alice", quota_bytes=100 * 1024**3, quota_cycle="monthly")
    return user


@pytest.fixture
def inbounds(db):
    return initialize_inbounds(enable=("vless", "shadowsocks"))


@pytest.fixture
def vless_inbound(inbounds):
    return next(item for item in inbounds if item.kind == Inbound.Kind.VLESS)


@pytest.fixture
def certificate(db):
    return generate_self_signed("vpn.example.com")


@pytest.fixture
def api_key(db, admin_user):
    from ostium.accounts.models import ApiKey

    key, plaintext = ApiKey.objects.create_key(name="tests", scope=ApiKey.Scope.WRITE, created_by=admin_user)
    return key, plaintext


@pytest.fixture
def api_client(api_key):
    from rest_framework.test import APIClient

    _key, plaintext = api_key
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {plaintext}")
    return client
