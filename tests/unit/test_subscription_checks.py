"""Unit coverage for subscription profile checks."""

from __future__ import annotations

import json

import pytest

import ostium.subscriptions.checks as checks
from ostium.proxy.models import Inbound
from ostium.subscriptions.checks import (
    FAIL,
    PASS,
    CheckResult,
    _binary_checks,
    _check_clash,
    _check_singbox,
    _check_uris,
    _xray_config,
)
from ostium.subscriptions.endpoints import build_endpoints


@pytest.fixture
def all_inbounds(inbounds, certificate):
    hysteria = Inbound.objects.get(kind="hysteria2")
    hysteria.certificate = certificate
    hysteria.enabled = True
    hysteria.save()
    trojan = Inbound.objects.get(kind="trojan")
    trojan.certificate = certificate
    trojan.enabled = True
    trojan.port = 8444
    trojan.save()
    return inbounds


def test_check_result_ok():
    assert CheckResult("x", "x", PASS, "").ok is True
    assert CheckResult("x", "x", "skip", "").ok is True
    assert CheckResult("x", "x", FAIL, "").ok is False


def test_clash_check_rejects_bad_shapes(monkeypatch):
    monkeypatch.setattr(checks, "render_clash", lambda endpoints: "[")
    assert _check_clash([]).status == FAIL

    monkeypatch.setattr(checks, "render_clash", lambda endpoints: "[]")
    assert _check_clash([]).status == FAIL

    monkeypatch.setattr(checks, "render_clash", lambda endpoints: "dns: {}\nrules: []\nproxies: []\n")
    assert _check_clash([]).status == FAIL

    monkeypatch.setattr(checks, "render_clash", lambda endpoints: "rules: [MATCH,Ostium]\nproxies: []\n")
    assert _check_clash([object()]).status == FAIL


def test_singbox_check_rejects_bad_shapes(monkeypatch):
    monkeypatch.setattr(checks, "render_singbox", lambda endpoints: "{")
    assert _check_singbox([]).status == FAIL

    monkeypatch.setattr(checks, "render_singbox", lambda endpoints: '{"dns": {}}')
    assert _check_singbox([]).status == FAIL

    monkeypatch.setattr(checks, "render_singbox", lambda endpoints: '{"route": {"default_domain_resolver": "x"}}')
    assert _check_singbox([]).status == FAIL

    monkeypatch.setattr(checks, "render_singbox", lambda endpoints: '{"route": {"final": "direct"}, "outbounds": []}')
    assert _check_singbox([]).status == FAIL

    monkeypatch.setattr(checks, "render_singbox", lambda endpoints: '{"route": {"final": "Ostium"}, "outbounds": []}')
    assert _check_singbox([object()]).status == FAIL


def test_uri_check_rejects_bad_shapes(monkeypatch):
    monkeypatch.setattr(checks, "render_uri_list", lambda endpoints: "")
    assert _check_uris([object()]).status == FAIL

    monkeypatch.setattr(checks, "render_uri_list", lambda endpoints: "ftp://x\n")
    monkeypatch.setattr(checks, "render_base64", lambda endpoints: "ZnRwOi8veAo=")
    assert _check_uris([object()]).status == FAIL

    monkeypatch.setattr(checks, "render_uri_list", lambda endpoints: "vless://x\n")
    monkeypatch.setattr(checks, "render_base64", lambda endpoints: "YmFk")
    assert _check_uris([object()]).status == FAIL


@pytest.mark.django_db
def test_xray_config_covers_supported_protocols(proxy_user, all_inbounds):
    endpoints = build_endpoints(proxy_user, "vpn.example.com")
    payload = _xray_config(endpoints)
    assert payload is not None
    assert {item["protocol"] for item in payload["outbounds"]} == {"vless", "trojan", "shadowsocks"}
    assert "hysteria2" not in {item["protocol"] for item in payload["outbounds"]}


def test_binary_checks_can_be_disabled():
    results = _binary_checks([], enabled=False)
    assert [item.status for item in results] == ["skip", "skip", "skip"]


def test_binary_checks_with_missing_binaries(monkeypatch):
    monkeypatch.setattr(checks, "_binary", lambda name, setting=None: None)
    results = _binary_checks([], enabled=True)
    assert {item.key for item in results} == {"mihomo", "singbox-bin", "xray"}
    assert all(item.status == "skip" for item in results)


def test_binary_checks_with_fake_binaries(monkeypatch):
    monkeypatch.setattr(checks, "_binary", lambda name, setting=None: "/bin/true")
    monkeypatch.setattr(checks, "_run", lambda command, timeout=30: (True, "通过"))
    monkeypatch.setattr(checks, "_xray_config", lambda endpoints: {"outbounds": []})
    results = _binary_checks([], enabled=True)
    assert all(item.status == PASS for item in results)


def test_json_cli_output(proxy_user, vless_inbound, capsys):
    from django.core.management import call_command

    call_command("subscription", "check", "--user", proxy_user.name, "--json", "--no-binaries")
    payload = json.loads(capsys.readouterr().out)
    assert payload["user"] == proxy_user.name
    assert payload["ok"] is True
    assert payload["checks"]
