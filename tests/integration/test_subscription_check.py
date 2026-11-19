"""Subscription compatibility self-check coverage."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from ostium.subscriptions.checks import FAIL, PASS, check_subscription


@pytest.mark.django_db
def test_check_subscription_structural_checks(proxy_user, vless_inbound):
    results = check_subscription(proxy_user, host="vpn.example.com", run_binaries=False)
    assert {result.key for result in results} >= {"endpoints", "clash", "singbox", "uri"}
    assert all(result.status != FAIL for result in results)
    assert all(result.status == PASS for result in results if result.key in {"endpoints", "clash", "singbox", "uri"})


@pytest.mark.django_db
def test_check_subscription_without_inbound(proxy_user, inbounds):
    for inbound in inbounds:
        inbound.enabled = False
        inbound.save(update_fields=["enabled"])
    results = check_subscription(proxy_user, host="vpn.example.com", run_binaries=False)
    assert results[0].key == "endpoints"
    assert results[0].status == FAIL


@pytest.mark.django_db
def test_subscription_check_page(admin_client, proxy_user, vless_inbound):
    response = admin_client.get(reverse("console:subscription_check", args=[proxy_user.pk]))
    assert response.status_code == 200
    body = response.content.decode()
    assert "订阅兼容性自检" in body
    assert "Clash / Mihomo YAML" in body
    assert "URI / Base64" in body


@pytest.mark.django_db
def test_subscription_check_command(proxy_user, vless_inbound, capsys):
    call_command("subscription", "check", "--user", proxy_user.name, "--no-binaries")
    output = capsys.readouterr().out
    assert "Subscription check: alice" in output
    assert "[PASS]" in output
    assert "Result: PASS" in output


@pytest.mark.django_db
def test_subscription_check_command_unknown_user():
    with pytest.raises(CommandError):
        call_command("subscription", "check", "--user", "missing", "--no-binaries")
