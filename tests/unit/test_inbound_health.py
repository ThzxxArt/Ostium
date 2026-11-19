"""Inbound health and anti-blocking action coverage."""

from __future__ import annotations

import socket
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from ostium.certificates.services import generate_self_signed
from ostium.engine.worker import Worker
from ostium.operations.models import Alert, RuntimeState
from ostium.proxy.health import (
    InboundHealth,
    _connections,
    _listening,
    _occupied_ports,
    _target_reachable,
    check_inbounds,
    pick_random_port,
    pick_reality_target,
)
from ostium.proxy.models import Inbound
from ostium.proxy.services import initialize_inbounds


@pytest.fixture
def all_health_inbounds(db):
    records = initialize_inbounds(enable=("vless", "hysteria2", "trojan", "shadowsocks"))
    by_kind = {item.kind: item for item in records}
    certificate = generate_self_signed("health.example.com")
    by_kind["hysteria2"].certificate = certificate
    by_kind["hysteria2"].port = 18443
    by_kind["hysteria2"].save()
    by_kind["trojan"].certificate = certificate
    by_kind["trojan"].port = 18444
    by_kind["trojan"].save()
    by_kind["vless"].port = 18445
    by_kind["vless"].save()
    by_kind["shadowsocks"].port = 18446
    by_kind["shadowsocks"].save()
    return by_kind


def _fake_connections(records):
    connections = []
    for record in records.values():
        if not record.enabled:
            continue
        kind = socket.SOCK_DGRAM if record.kind == Inbound.Kind.HYSTERIA2 else socket.SOCK_STREAM
        status = "NONE" if kind == socket.SOCK_DGRAM else "LISTEN"
        connections.append(
            SimpleNamespace(
                laddr=SimpleNamespace(port=record.port),
                type=kind,
                status=status,
            )
        )
    return connections


@pytest.mark.django_db
def test_check_inbounds_marks_all_healthy(all_health_inbounds):
    results = check_inbounds(connections=_fake_connections(all_health_inbounds), singbox_running=True)
    assert {item.status for item in results} == {"ok"}
    assert {item.kind for item in results} == {"vless", "hysteria2", "trojan", "shadowsocks"}


@pytest.mark.django_db
def test_check_inbounds_reports_unlistened_and_disabled(all_health_inbounds):
    connections = _fake_connections(all_health_inbounds)
    connections = [item for item in connections if item.laddr.port != all_health_inbounds["trojan"].port]
    all_health_inbounds["shadowsocks"].enabled = False
    all_health_inbounds["shadowsocks"].save(update_fields=["enabled"])
    results = {item.kind: item for item in check_inbounds(connections=connections, singbox_running=True)}
    assert results["trojan"].status == "fail"
    assert "未监听" in results["trojan"].detail
    assert results["shadowsocks"].status == "disabled"


@pytest.mark.django_db
def test_check_inbounds_warns_without_hysteria_obfs(all_health_inbounds):
    hysteria = all_health_inbounds["hysteria2"]
    hysteria.update_params(obfs_password="")
    hysteria.save()
    results = {
        item.kind: item
        for item in check_inbounds(connections=_fake_connections(all_health_inbounds), singbox_running=True)
    }
    assert results["hysteria2"].status == "warn"
    assert "salamander" in results["hysteria2"].detail


@pytest.mark.django_db
def test_pick_random_port_avoids_ostium_ports(all_health_inbounds):
    for record in all_health_inbounds.values():
        record.enabled = True
        record.save(update_fields=["enabled"])
    chosen = pick_random_port(all_health_inbounds["trojan"], connections=[])
    assert 20000 <= chosen <= 59999
    assert chosen not in {item.port for item in all_health_inbounds.values()}


def test_pick_reality_target_skips_current():
    target = pick_reality_target("www.microsoft.com", checker=lambda host: True)
    assert target != "www.microsoft.com"


def test_pick_reality_target_reports_unreachable(monkeypatch):
    with pytest.raises(RuntimeError):
        pick_reality_target(None, checker=lambda host: False)


@pytest.mark.django_db
def test_worker_alerts_unhealthy_inbound(monkeypatch):
    state = RuntimeState.load()
    state.singbox_running = True
    state.singbox_started_at = timezone.now() - timedelta(minutes=1)
    state.save()
    monkeypatch.setattr(
        "ostium.proxy.health.check_inbounds",
        lambda **kwargs: [InboundHealth("vless", "Reality", "fail", "端口未监听", "检查端口")],
    )
    Worker()._check_inbounds()
    assert Alert.objects.filter(code="inbound_unhealthy").exists()


def test_connections_falls_back_on_permission_error(monkeypatch):
    import psutil

    def fail(**kwargs):
        raise psutil.Error("denied")

    monkeypatch.setattr("psutil.net_connections", fail)
    assert _connections() == []


@pytest.mark.django_db
def test_listening_filters_address_type_and_state(all_health_inbounds):
    record = all_health_inbounds["vless"]
    assert not _listening(record, [SimpleNamespace(laddr=None, type=socket.SOCK_STREAM, status="LISTEN")])
    assert not _listening(
        record,
        [SimpleNamespace(laddr=SimpleNamespace(port=record.port), type=socket.SOCK_DGRAM, status="NONE")],
    )
    assert not _listening(
        record,
        [SimpleNamespace(laddr=SimpleNamespace(port=record.port), type=socket.SOCK_STREAM, status="ESTABLISHED")],
    )
    assert _listening(
        record,
        [SimpleNamespace(laddr=SimpleNamespace(port=record.port), type=socket.SOCK_STREAM, status="LISTEN")],
    )


@pytest.mark.django_db
def test_check_inbounds_reports_singbox_down_and_invalid_config(all_health_inbounds):
    results = check_inbounds(connections=[], singbox_running=False)
    assert results and all(item.status == "fail" for item in results)

    trojan = all_health_inbounds["trojan"]
    trojan.certificate = None
    trojan.save(update_fields=["certificate"])
    results = {item.kind: item for item in check_inbounds(connections=[], singbox_running=True)}
    assert results["trojan"].status == "fail"
    assert "证书" in results["trojan"].detail


def test_occupied_ports_ignores_unbound_sockets():
    assert _occupied_ports([SimpleNamespace(laddr=None, type=socket.SOCK_STREAM)]) == set()


def test_target_reachable_handles_success_and_failure(monkeypatch):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("ostium.proxy.health.socket.create_connection", lambda *args, **kwargs: Connection())
    assert _target_reachable("example.com") is True

    def fail(*args, **kwargs):
        raise OSError("unreachable")

    monkeypatch.setattr("ostium.proxy.health.socket.create_connection", fail)
    assert _target_reachable("example.com") is False


@pytest.mark.django_db
def test_pick_random_port_reads_live_listeners(all_health_inbounds):
    assert 20000 <= pick_random_port(all_health_inbounds["shadowsocks"]) <= 59999


@pytest.mark.django_db
def test_pick_random_port_retries_occupied_port(all_health_inbounds, monkeypatch):
    values = iter([0, 1])
    monkeypatch.setattr("ostium.proxy.health.secrets.randbelow", lambda _: next(values))
    record = all_health_inbounds["shadowsocks"]
    occupied = [SimpleNamespace(laddr=SimpleNamespace(port=20000), type=socket.SOCK_STREAM, status="LISTEN")]
    chosen = pick_random_port(record, connections=occupied)
    assert chosen == 20001


@pytest.mark.django_db
def test_pick_random_port_raises_when_exhausted(all_health_inbounds, monkeypatch):
    monkeypatch.setattr("ostium.proxy.health.secrets.randbelow", lambda _: 0)
    record = all_health_inbounds["shadowsocks"]
    record.port = 20000
    record.save(update_fields=["port"])
    occupied = [SimpleNamespace(laddr=SimpleNamespace(port=20000), type=socket.SOCK_STREAM, status="LISTEN")]
    with pytest.raises(RuntimeError):
        pick_random_port(record, connections=occupied)


@pytest.mark.django_db
def test_worker_resolves_inbound_alert(monkeypatch):
    state = RuntimeState.load()
    state.singbox_running = True
    state.singbox_started_at = timezone.now() - timedelta(minutes=1)
    state.save()
    monkeypatch.setattr(
        "ostium.proxy.health.check_inbounds",
        lambda **kwargs: [InboundHealth("vless", "Reality", "fail", "端口未监听", "检查端口")],
    )
    Worker()._check_inbounds()
    monkeypatch.setattr(
        "ostium.proxy.health.check_inbounds",
        lambda **kwargs: [InboundHealth("vless", "Reality", "ok", "端口正常", "")],
    )
    Worker()._check_inbounds()
    alert = Alert.objects.get(code="inbound_unhealthy")
    assert alert.resolved_at is not None


@pytest.mark.django_db
def test_worker_skips_inbound_check_when_singbox_stopped(monkeypatch):
    state = RuntimeState.load()
    state.singbox_running = False
    state.save()
    called = []
    monkeypatch.setattr("ostium.proxy.health.check_inbounds", lambda **kwargs: called.append(True))
    Worker()._check_inbounds()
    assert not called


@pytest.mark.django_db
def test_inbound_check_cli_json(capsys):
    from django.core.management import call_command

    call_command("inbound", "check", "--json")
    assert "[]" in capsys.readouterr().out


@pytest.mark.django_db
def test_console_inbound_action_errors(admin_client, all_health_inbounds, monkeypatch):
    from django.urls import reverse

    monkeypatch.setattr(
        "ostium.operations.console_views.pick_random_port",
        lambda record: (_ for _ in ()).throw(RuntimeError("no port")),
    )
    response = admin_client.post(
        reverse("console:inbounds"),
        {"kind": "trojan", "action": "randomize_port"},
        follow=True,
    )
    assert response.status_code == 200
    assert "no port" in response.content.decode()

    response = admin_client.post(
        reverse("console:inbounds"),
        {"kind": "trojan", "action": "rotate_camouflage"},
    )
    assert response.status_code == 400

    monkeypatch.setattr(
        "ostium.operations.console_views.pick_reality_target",
        lambda current: (_ for _ in ()).throw(RuntimeError("no target")),
    )
    response = admin_client.post(
        reverse("console:inbounds"),
        {"kind": "vless", "action": "rotate_camouflage"},
        follow=True,
    )
    assert response.status_code == 200
    assert "no target" in response.content.decode()


@pytest.mark.django_db
def test_console_inbound_health_and_actions(admin_client, all_health_inbounds, monkeypatch):
    from django.urls import reverse

    response = admin_client.get(reverse("console:inbound_health"))
    assert response.status_code == 200
    assert "线路健康与防封禁" in response.content.decode()

    monkeypatch.setattr("ostium.operations.console_views.pick_random_port", lambda record: 23456)
    response = admin_client.post(
        reverse("console:inbounds"),
        {"kind": "trojan", "action": "randomize_port"},
    )
    assert response.status_code == 302
    all_health_inbounds["trojan"].refresh_from_db()
    assert all_health_inbounds["trojan"].port == 23456

    monkeypatch.setattr("ostium.operations.console_views.pick_reality_target", lambda current: "www.apple.com")
    response = admin_client.post(
        reverse("console:inbounds"),
        {"kind": "vless", "action": "rotate_camouflage"},
    )
    assert response.status_code == 302
    all_health_inbounds["vless"].refresh_from_db()
    assert all_health_inbounds["vless"].params["server_name"] == "www.apple.com"
