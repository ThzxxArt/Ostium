"""Form validation tests."""

from __future__ import annotations

import pytest

from ostium.operations.forms import InboundForm, SettingsForm, UserEditForm
from ostium.proxy.models import Inbound


@pytest.mark.django_db
def test_user_form_parses_quota(proxy_user):
    form = UserEditForm(
        data={
            "name": "alice",
            "enabled": "on",
            "quota": "1.5G",
            "quota_cycle": "monthly",
            "note": "hello",
        },
        instance=proxy_user,
    )
    assert form.is_valid(), form.errors
    user = form.save()
    assert user.quota_bytes == int(1.5 * 1024**3)


@pytest.mark.django_db
def test_user_form_rejects_bad_quota_and_duplicate(proxy_user):
    _other, _ = __import__("ostium.proxy.services", fromlist=["create_proxy_user"]).create_proxy_user("bob")
    form = UserEditForm(data={"name": "bob", "quota": "nope", "quota_cycle": "total"}, instance=proxy_user)
    assert form.is_valid() is False
    assert "name" in form.errors
    assert "quota" in form.errors


@pytest.mark.django_db
def test_user_form_blank_quota(proxy_user):
    form = UserEditForm(
        data={"name": "alice", "quota": "", "quota_cycle": "total"},
        instance=proxy_user,
    )
    assert form.is_valid(), form.errors
    assert form.save().quota_bytes == 0


def test_user_form_expiry_input(proxy_user):
    form = UserEditForm(instance=proxy_user)
    assert form.fields["expires_at"].input_formats


@pytest.mark.django_db
def test_inbound_form_requires_certificate(inbounds):
    inbound = Inbound.objects.get(kind="hysteria2")
    form = InboundForm(data={"enabled": "on", "listen": "0.0.0.0", "port": 443}, instance=inbound)
    assert form.is_valid() is False
    assert "certificate" in form.errors


@pytest.mark.django_db
def test_inbound_form_rejects_bad_port(inbounds):
    inbound = Inbound.objects.get(kind="vless")
    form = InboundForm(data={"enabled": "on", "listen": "0.0.0.0", "port": 70000}, instance=inbound)
    assert form.is_valid() is False


@pytest.mark.django_db
def test_settings_form_validation(settings):
    form = SettingsForm(
        data={
            "server_name": "x",
            "server_dns_mode": "auto",
            "server_dns_doh_url": "http://insecure",
            "webhook_url": "http://insecure",
            "log_level": "info",
            "subscription_update_interval": "24",
            "traffic_retention_days": "90",
            "audit_retention_days": "365",
            "auto_backup_keep": "7",
        }
    )
    assert form.is_valid() is False
    assert "server_dns_doh_url" in form.errors
    assert "webhook_url" in form.errors


@pytest.mark.django_db
def test_settings_form_saves(settings):
    form = SettingsForm(
        data={
            "server_name": "Unit",
            "public_host": "vpn.example.com",
            "public_base_url": "https://vpn.example.com/",
            "server_dns_mode": "udp",
            "server_dns_doh_url": "https://1.1.1.1/dns-query",
            "log_level": "debug",
            "subscription_update_interval": "12",
            "traffic_retention_days": "30",
            "audit_retention_days": "90",
            "auto_backup_keep": "3",
        }
    )
    assert form.is_valid(), form.errors
    updated = form.save()
    assert "server_name" in updated
    from constance import config

    assert config.server_name == "Unit"
    assert config.public_base_url == "https://vpn.example.com"


class _Noop:
    pass
