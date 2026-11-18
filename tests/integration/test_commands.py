"""Management command tests."""

from __future__ import annotations

import io
import json

import pytest
from django.core.management import call_command

from ostium.accounts.models import ApiKey
from ostium.proxy.models import Inbound, ProxyUser


@pytest.mark.django_db
def test_user_add_and_list():
    out = io.StringIO()
    call_command("user", "add", "bob", "--quota", "2G", "--json", stdout=out)
    payload = json.loads(out.getvalue())
    assert payload["name"] == "bob"
    assert ProxyUser.objects.get(name="bob").quota_bytes == 2 * 1024**3

    out = io.StringIO()
    call_command("user", "list", "--json", stdout=out)
    assert json.loads(out.getvalue())[0]["name"] == "bob"


@pytest.mark.django_db
def test_user_lifecycle_commands(proxy_user):
    call_command("user", "disable", proxy_user.name, stdout=io.StringIO())
    proxy_user.refresh_from_db()
    assert proxy_user.enabled is False
    call_command("user", "enable", proxy_user.name, stdout=io.StringIO())
    proxy_user.refresh_from_db()
    assert proxy_user.enabled is True
    old = proxy_user.reveal_subscription_token()
    call_command("user", "rotate", proxy_user.name, "--subscription", stdout=io.StringIO())
    proxy_user.refresh_from_db()
    assert proxy_user.reveal_subscription_token() != old
    call_command("user", "reset-usage", proxy_user.name, stdout=io.StringIO())
    call_command("user", "delete", proxy_user.name, stdout=io.StringIO())
    assert not ProxyUser.objects.filter(name=proxy_user.name).exists()


@pytest.mark.django_db
def test_inbound_commands(inbounds):
    call_command("inbound", "set-port", "vless", "8443", stdout=io.StringIO())
    assert Inbound.objects.get(kind="vless").port == 8443
    call_command("inbound", "rotate-keys", "vless", stdout=io.StringIO())
    call_command("inbound", "disable", "vless", stdout=io.StringIO())
    assert Inbound.objects.get(kind="vless").enabled is False
    call_command("inbound", "enable", "vless", stdout=io.StringIO())
    assert Inbound.objects.get(kind="vless").enabled is True


@pytest.mark.django_db
def test_init_command():
    out = io.StringIO()
    call_command("init", "--username", "root", "--password", "Init-Password-2026", stdout=out)
    assert "Ostium initialized" in out.getvalue()
    assert ProxyUser.objects.count() == 0
    assert Inbound.objects.count() == 4
    assert Inbound.objects.get(kind="vless").enabled is True
    from django.contrib.auth import get_user_model

    assert get_user_model().objects.get(username="root").is_superuser


@pytest.mark.django_db
def test_status_apply_token_commands(admin_user, inbounds):
    out = io.StringIO()
    call_command("status", "--json", stdout=out)
    payload = json.loads(out.getvalue())
    from ostium.version import __version__

    assert payload["version"] == __version__
    assert len(payload["inbounds"]) == 4

    call_command("apply", stdout=io.StringIO())
    from ostium.operations.models import RuntimeState

    assert RuntimeState.load().desired_revision >= 1

    out = io.StringIO()
    call_command("token", "create", "ci", "--scope", "read", "--json", stdout=out)
    payload = json.loads(out.getvalue())
    assert payload["scope"] == "read"
    assert ApiKey.objects.filter(name="ci").exists()
    call_command("token", "revoke", payload["prefix"], stdout=io.StringIO())
    assert ApiKey.objects.get(name="ci").revoked is True


@pytest.mark.django_db
def test_diagnostics_command(tmp_path):
    path = tmp_path / "diag.tar.gz"
    call_command("diagnostics", "--output", str(path), stdout=io.StringIO())
    assert path.is_file()
    assert path.read_bytes()[:2] == b"\x1f\x8b"
