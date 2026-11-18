"""All user command output paths."""

from __future__ import annotations

import io
import json

import pytest
from django.core.management.base import CommandError

from ostium.proxy.models import ProxyUser


@pytest.mark.django_db
def test_user_command_outputs(capsys):
    call_command_ = __import__("django.core.management", fromlist=["call_command"]).call_command
    call_command_("user", "add", "alice", "--quota", "1G", stdout=io.StringIO())
    with pytest.raises(CommandError):
        call_command_("user", "add", "alice", stdout=io.StringIO())
    with pytest.raises(CommandError):
        call_command_("user", "add", "bad", "--quota", "nope", stdout=io.StringIO())

    out = io.StringIO()
    call_command_("user", "list", stdout=out)
    assert "alice" in out.getvalue()
    out = io.StringIO()
    call_command_("user", "show", "alice", stdout=out)
    assert "quota_bytes" in out.getvalue()
    out = io.StringIO()
    call_command_("user", "show", "alice", "--json", stdout=out)
    assert json.loads(out.getvalue())["name"] == "alice"

    out = io.StringIO()
    call_command_("user", "subscription", "alice", stdout=out)
    assert "Use --reveal" in out.getvalue()
    out = io.StringIO()
    call_command_("user", "subscription", "alice", "--reveal", stdout=out)
    assert "Base64" in out.getvalue()
    out = io.StringIO()
    call_command_("user", "subscription", "alice", "--reveal", "--json", stdout=out)
    assert json.loads(out.getvalue())["links"]

    call_command_("user", "rotate", "alice", "--credentials", stdout=io.StringIO())
    with pytest.raises(CommandError):
        call_command_("user", "show", "missing", stdout=io.StringIO())


@pytest.mark.django_db
def test_user_command_expiry_and_disabled():
    from django.core.management import call_command

    call_command(
        "user",
        "add",
        "future",
        "--expires",
        "2030-01-01T00:00:00Z",
        "--disabled",
        "--note",
        "n",
        stdout=io.StringIO(),
    )
    user = ProxyUser.objects.get(name="future")
    assert user.enabled is False
    assert user.expires_at is not None
    with pytest.raises(CommandError):
        call_command("user", "add", "bad-date", "--expires", "nope", stdout=io.StringIO())
