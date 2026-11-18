"""Command branches and CLI entry point."""

from __future__ import annotations

import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from ostium.proxy.models import Inbound


@pytest.mark.django_db
def test_status_text(admin_user, inbounds):
    out = io.StringIO()
    call_command("status", stdout=out)
    assert "Ostium Server" in out.getvalue()
    assert "vless" in out.getvalue()


@pytest.mark.django_db
def test_init_rejects_duplicate(admin_user):
    with pytest.raises(CommandError):
        call_command("init", "--username", "admin", "--password", "Init-Password-2026", stdout=io.StringIO())


@pytest.mark.django_db
def test_init_rejects_weak_password():
    with pytest.raises(CommandError):
        call_command("init", "--username", "newadmin", "--password", "short", stdout=io.StringIO())


@pytest.mark.django_db
def test_init_with_domain(inbounds):
    call_command(
        "init",
        "--username",
        "root",
        "--password",
        "Init-Password-2026",
        "--domain",
        "https://vpn.example.com/",
        stdout=io.StringIO(),
    )
    from constance import config

    assert config.public_host == "vpn.example.com"


@pytest.mark.django_db
def test_inbound_commands_more(inbounds, certificate):
    out = io.StringIO()
    call_command("inbound", "list", stdout=out)
    assert "vless" in out.getvalue()
    call_command(
        "inbound",
        "enable",
        "hysteria2",
        "--cert",
        "vpn.example.com",
        stdout=io.StringIO(),
    )
    assert Inbound.objects.get(kind="hysteria2").enabled is True
    with pytest.raises(CommandError):
        call_command("inbound", "set-port", "vless", "70000")
    with pytest.raises(CommandError):
        call_command("inbound", "enable", "trojan", stdout=io.StringIO())
    with pytest.raises(CommandError):
        call_command("inbound", "disable", "nope")


@pytest.mark.django_db
def test_cert_command_errors(certificate, tmp_path):
    with pytest.raises(CommandError):
        call_command(
            "cert",
            "import",
            "--domain",
            "vpn.example.com",
            "--cert",
            "/nonexistent",
            "--key",
            "/nonexistent",
            stdout=io.StringIO(),
        )
    with pytest.raises(CommandError):
        call_command("cert", "delete", "missing.example.com", stdout=io.StringIO())
    inbound = Inbound.objects.get(kind="hysteria2") if Inbound.objects.exists() else None
    if inbound is None:
        from ostium.proxy.services import initialize_inbounds

        initialize_inbounds()
        inbound = Inbound.objects.get(kind="hysteria2")
    inbound.certificate = certificate
    inbound.save()
    with pytest.raises(CommandError):
        call_command("cert", "delete", certificate.domain, stdout=io.StringIO())


@pytest.mark.django_db
def test_doctor_text():
    with pytest.raises(SystemExit):
        call_command("doctor", stdout=io.StringIO())


def test_cli_entrypoint(monkeypatch):
    from ostium import cli

    called = {}
    monkeypatch.setattr(
        "django.core.management.execute_from_command_line", lambda argv: called.setdefault("argv", argv)
    )
    cli.main(["status"])
    assert called["argv"] == ["ostium", "status"]
