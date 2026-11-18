"""DNS, config branches and binary check tests."""

from __future__ import annotations

import subprocess

import pytest

from ostium.engine import dns as dns_module
from ostium.engine.config import (
    ConfigError,
    _check_port_conflicts,
    _reality_tls,
    check_config,
    generate_config,
    is_private_address,
)
from ostium.engine.dns import DNSError, build_dns_plan, doh_available
from ostium.proxy.models import Inbound


@pytest.mark.django_db
def test_dns_modes(monkeypatch):
    monkeypatch.setattr(dns_module, "doh_available", lambda url, timeout=3.0: True)
    plan = build_dns_plan(mode="auto", probe=True)
    assert plan.effective_mode == "doh"
    assert plan.final == "remote"
    plan = build_dns_plan(mode="udp", probe=True)
    assert plan.effective_mode == "udp"
    plan = build_dns_plan(mode="doh", probe=True)
    assert plan.effective_mode == "doh"


@pytest.mark.django_db
def test_dns_fallback_and_fail_closed(monkeypatch):
    monkeypatch.setattr(dns_module, "doh_available", lambda url, timeout=3.0: False)
    plan = build_dns_plan(mode="auto", probe=True)
    assert plan.effective_mode == "udp"
    assert plan.warning
    with pytest.raises(DNSError):
        build_dns_plan(mode="doh", probe=True)


@pytest.mark.django_db
def test_dns_rejects_bad_url():
    with pytest.raises(DNSError):
        build_dns_plan(mode="doh", url="http://example.com/dns-query", probe=False)
    with pytest.raises(DNSError):
        build_dns_plan(mode="doh", url="https://user:pass@example.com/dns-query", probe=False)


def test_doh_available_false(monkeypatch):
    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, *args, **kwargs):
            raise dns_module.httpx.ConnectError("nope")

    monkeypatch.setattr(dns_module.httpx, "Client", Client)
    assert doh_available("https://1.1.1.1/dns-query") is False


@pytest.mark.django_db
def test_reality_tls_defaults():
    block = _reality_tls({"private_key": "key"})
    assert block["server_name"] == "www.microsoft.com"
    assert block["reality"]["handshake"]["server_port"] == 443


@pytest.mark.django_db
def test_vless_missing_key(proxy_user, inbounds):
    vless = Inbound.objects.get(kind="vless")
    vless.update_params(private_key="", public_key="")
    vless.save()
    with pytest.raises(ConfigError):
        generate_config(probe_dns=False)


@pytest.mark.django_db
def test_shadowsocks_missing_key(proxy_user, inbounds):
    ss = Inbound.objects.get(kind="shadowsocks")
    ss.update_params(server_key="")
    ss.save()
    with pytest.raises(ConfigError):
        generate_config(probe_dns=False)


def test_port_conflicts():
    class Fake:
        def __init__(self, kind, port):
            self.kind = kind
            self.port = port

    with pytest.raises(ConfigError):
        _check_port_conflicts([Fake("vless", 443), Fake("trojan", 443)])
    _check_port_conflicts([Fake("vless", 443), Fake("hysteria2", 443)])
    with pytest.raises(ConfigError):
        _check_port_conflicts([Fake("hysteria2", 443), Fake("hysteria2", 443)])


def test_is_private_address():
    assert is_private_address("127.0.0.1")
    assert is_private_address("10.0.0.1")
    assert not is_private_address("1.1.1.1")
    assert not is_private_address("not-an-ip")


def test_check_config_missing_binary(tmp_path):
    ok, message = check_config("/nonexistent/sing-box", tmp_path / "x.json", timeout=1)
    assert ok is False
    assert message


def test_check_config_true(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{}")
    ok, _message = check_config("/bin/true", path, timeout=1)
    assert ok is True


def test_check_config_false(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{}")
    ok, _message = check_config("/bin/false", path, timeout=1)
    assert ok is False


def test_check_config_timeout(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text("{}")

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("sing-box", 1)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    ok, message = check_config("/bin/true", path, timeout=1)
    assert ok is False
    assert "timed out" in message.lower()
