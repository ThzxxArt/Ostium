"""Coverage boosters for commands, serializers and model branches."""

from __future__ import annotations

import io
import tarfile
from datetime import timedelta
from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from ostium.api.serializers import InboundSerializer, ProxyUserCreateSerializer
from ostium.proxy.models import Inbound, ProxyUser


@pytest.mark.django_db
def test_token_command_text(admin_user):
    out = io.StringIO()
    call_command("token", "create", "text-key", "--scope", "write", stdout=out)
    assert "text-key" in out.getvalue()
    call_command("token", "list", stdout=io.StringIO())
    call_command("token", "list", "--json", stdout=io.StringIO())
    from ostium.accounts.models import ApiKey

    prefix = ApiKey.objects.get(name="text-key").prefix
    call_command("token", "revoke", prefix, stdout=io.StringIO())
    with pytest.raises(CommandError):
        call_command("token", "revoke", "nope", stdout=io.StringIO())


@pytest.mark.django_db
def test_backup_command_missing_password():
    with pytest.raises(CommandError):
        call_command("backup", "create", stdout=io.StringIO())
    call_command("backup", "list", stdout=io.StringIO())


def test_version_fallbacks(monkeypatch):
    from importlib.metadata import PackageNotFoundError

    from ostium import version

    def missing(name):
        raise PackageNotFoundError

    monkeypatch.setattr(version, "version", missing)
    monkeypatch.setattr(version, "_read_version_file", lambda: "9.9.9")
    assert version.get_version() == "9.9.9"
    monkeypatch.setattr(version, "_read_version_file", lambda: None)
    assert version.get_version() == version._FALLBACK


def test_serializer_validation(db):
    serializer = ProxyUserCreateSerializer(data={"name": ""})
    assert serializer.is_valid() is False
    ProxyUser.objects.create(name="dup")
    serializer = ProxyUserCreateSerializer(data={"name": "dup"})
    assert serializer.is_valid() is False
    serializer = ProxyUserCreateSerializer(
        data={"name": "future", "expires_at": (timezone.now() - timedelta(days=1)).isoformat()}
    )
    assert serializer.is_valid() is False
    serializer = ProxyUserCreateSerializer(data={"name": "ok", "quota_bytes": 10})
    assert serializer.is_valid(), serializer.errors
    assert serializer.save().name == "ok"


@pytest.mark.django_db
def test_inbound_serializer_validation(inbounds):
    inbound = Inbound.objects.get(kind="hysteria2")
    serializer = InboundSerializer(inbound, data={"certificate_domain": "missing"}, partial=True)
    assert serializer.is_valid() is False
    serializer = InboundSerializer(inbound, data={"enabled": True}, partial=True)
    assert serializer.is_valid() is False


@pytest.mark.django_db
def test_proxy_model_branches(proxy_user):
    old_uuid = proxy_user.uuid
    proxy_user.rotate_credentials(rotate_uuid=False)
    assert proxy_user.uuid == old_uuid
    proxy_user.disable()
    proxy_user.refresh_from_db()
    assert proxy_user.status == "disabled"
    proxy_user.enable()
    proxy_user.refresh_from_db()
    assert proxy_user.status == "active"
    proxy_user.quota_cycle = ProxyUser.QuotaCycle.TOTAL
    assert proxy_user.roll_month_if_needed() is False


@pytest.mark.django_db
def test_inbound_validation_errors(inbounds):
    inbound = Inbound.objects.get(kind="vless")
    inbound.port = 70000
    assert inbound.validation_errors()
    with pytest.raises(ValidationError):
        inbound.clean()
    ss = Inbound.objects.get(kind="shadowsocks")
    ss.update_params(method="aes-128-gcm")
    with pytest.raises(ValidationError):
        ss.clean()


def test_formatting_aware_datetime():
    from django.utils import timezone

    from ostium.formatting import format_datetime

    assert format_datetime(timezone.now()).count(":") == 1


@pytest.mark.django_db
def test_config_dns_warning(monkeypatch, proxy_user, vless_inbound):
    from ostium.engine import config as config_module

    class Plan:
        servers = [{"type": "udp", "tag": "local", "server": "1.1.1.1"}]
        final = "local"
        effective_mode = "udp"
        warning = "fallback"

    monkeypatch.setattr(config_module, "build_dns_plan", lambda probe=True: Plan())
    result = config_module.generate_config(probe_dns=True)
    assert result.warnings == ["fallback"]


@pytest.mark.django_db
def test_stats_query_failure(monkeypatch):
    import grpc

    from ostium.engine import stats as stats_module

    class Call:
        def __call__(self, *args, **kwargs):
            raise grpc.RpcError()

    class Channel:
        def unary_unary(self, *args, **kwargs):
            return Call()

        def close(self):
            pass

    monkeypatch.setattr(stats_module.grpc, "insecure_channel", lambda address: Channel())
    with pytest.raises(stats_module.StatsUnavailable):
        stats_module.query_stats()


def test_backup_malicious_archive(tmp_path, settings):
    import os

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from ostium.operations.backup import MAGIC, BackupError, _derive, restore_file

    settings.OSTIUM_DATA_DIR = str(tmp_path)
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("../evil")
        info.size = 1
        tar.addfile(info, BytesIO(b"x"))
    payload = buffer.getvalue()
    salt = os.urandom(16)
    nonce = os.urandom(12)
    blob = MAGIC + salt + nonce + AESGCM(_derive("a-long-backup-password", salt)).encrypt(nonce, payload, MAGIC)
    path = tmp_path / "bad.ostb"
    path.write_bytes(blob)
    with pytest.raises(BackupError):
        restore_file(path, password="a-long-backup-password")


@pytest.mark.django_db
def test_subscription_token_rate_limit(client, proxy_user, vless_inbound):
    from django.core.cache import cache

    from ostium.proxy.models import hash_subscription_token

    token = proxy_user.reveal_subscription_token()
    cache.set(f"ostium:sub:rate:{hash_subscription_token(token)}", 200, 60)
    response = client.get(f"/sub/{token}")
    assert response.status_code == 429
    assert response["Retry-After"] == "60"


@pytest.mark.django_db
def test_operations_services(admin_user, settings):
    from ostium.operations.models import AuditEvent
    from ostium.operations.services import acknowledge_alert, client_ip, raise_alert, record_audit, resolve_alert

    class Request:
        user = admin_user
        META = {"REMOTE_ADDR": "1.2.3.4", "HTTP_USER_AGENT": "ua", "HTTP_X_FORWARDED_FOR": "5.6.7.8"}

    settings.OSTIUM_BEHIND_PROXY = True
    assert client_ip(Request()) == "5.6.7.8"
    event = record_audit(action="test", request=Request(), target="x")
    assert AuditEvent.objects.filter(pk=event.pk).exists()
    alert = raise_alert(code="x", message="m", fingerprint="x")
    acknowledge_alert(alert)
    raise_alert(code="x", message="m2", fingerprint="x")
    alert.refresh_from_db()
    # Acknowledging an active condition survives periodic re-raises.
    assert alert.acknowledged_at is not None
    resolve_alert("x")
    alert.refresh_from_db()
    assert alert.resolved_at is not None
    raise_alert(code="x", message="m3", fingerprint="x")
    alert.refresh_from_db()
    assert alert.acknowledged_at is None
    assert alert.resolved_at is None
