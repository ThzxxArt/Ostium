"""Server configuration generation tests."""

from __future__ import annotations

import pytest

from ostium.engine.config import ConfigError, config_hash, generate_config, write_config
from ostium.proxy.models import Inbound


@pytest.mark.django_db
def test_generate_config(proxy_user, vless_inbound):
    result = generate_config(probe_dns=False)
    config = result.config
    assert config["inbounds"][0]["type"] == "vless"
    assert config["inbounds"][0]["users"][0]["name"] == proxy_user.name
    assert config["route"]["rules"][-1]["ip_is_private"] is True
    assert config["experimental"]["v2ray_api"]["stats"]["users"] == [proxy_user.name]
    assert result.sha256 == config_hash(config)
    assert result.effective_dns in {"doh", "udp"}


@pytest.mark.django_db
def test_disabled_user_is_excluded(proxy_user, vless_inbound):
    proxy_user.enabled = False
    proxy_user.save(update_fields=["enabled"])
    result = generate_config(probe_dns=False)
    assert result.config["inbounds"][0]["users"] == []


@pytest.mark.django_db
def test_expired_user_is_excluded(proxy_user, vless_inbound):
    from django.utils import timezone

    proxy_user.expires_at = timezone.now()
    proxy_user.save(update_fields=["expires_at"])
    result = generate_config(probe_dns=False)
    assert result.config["inbounds"][0]["users"] == []


@pytest.mark.django_db
def test_port_conflict(proxy_user, inbounds, certificate):
    trojan = Inbound.objects.get(kind="trojan")
    trojan.enabled = True
    trojan.certificate = certificate
    trojan.port = 443
    trojan.save()
    vless = Inbound.objects.get(kind="vless")
    vless.port = 443
    vless.save()
    with pytest.raises(ConfigError):
        generate_config(probe_dns=False)


@pytest.mark.django_db
def test_certificate_required(proxy_user, inbounds):
    hysteria = Inbound.objects.get(kind="hysteria2")
    hysteria.enabled = True
    hysteria.save()
    with pytest.raises(ConfigError) as exc:
        generate_config(probe_dns=False)
    assert "certificate" in str(exc.value).lower()


@pytest.mark.django_db
def test_private_egress_can_be_disabled(proxy_user, vless_inbound):
    from constance import config

    config.block_private_egress = False
    result = generate_config(probe_dns=False)
    assert not any(rule.get("ip_is_private") for rule in result.config["route"]["rules"])


@pytest.mark.django_db
def test_write_config_permissions(proxy_user, vless_inbound, tmp_path):
    result = generate_config(probe_dns=False)
    path = tmp_path / "config.json"
    write_config(path, result)
    assert path.is_file()
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert path.read_text().startswith("{")


@pytest.mark.django_db
def test_hash_is_canonical(proxy_user, vless_inbound):
    first = generate_config(probe_dns=False)
    second = generate_config(probe_dns=False)
    assert first.sha256 == second.sha256


@pytest.mark.django_db
def test_shadowsocks_uses_user_keys(proxy_user, inbounds):
    result = generate_config(probe_dns=False)
    ss = next(item for item in result.config["inbounds"] if item["type"] == "shadowsocks")
    assert ss["users"][0]["password"] == proxy_user.ss_password
    assert ss["password"] == Inbound.objects.get(kind="shadowsocks").params["server_key"]
