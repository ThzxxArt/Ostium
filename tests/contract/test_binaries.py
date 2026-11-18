"""Contract tests against the real pinned binaries."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from django.conf import settings

from ostium.engine.config import generate_config, write_config
from ostium.proxy.models import Inbound
from ostium.subscriptions.endpoints import build_endpoints
from ostium.subscriptions.renderers import render_clash, render_singbox

pytestmark = pytest.mark.contract


def _binary(path: str) -> str | None:
    candidate = Path(path)
    if candidate.is_file():
        return str(candidate)
    return shutil.which(Path(path).name)


@pytest.fixture
def singbox():
    binary = _binary(settings.OSTIUM_SINGBOX_PATH)
    if not binary:
        pytest.skip("sing-box binary is not installed")
    output = subprocess.run([binary, "version"], capture_output=True, text=True, check=False).stdout
    if "with_v2ray_api" not in output:
        pytest.skip("sing-box was built without with_v2ray_api")
    return binary


@pytest.fixture
def mihomo():
    binary = _binary(str(Path(".cache/bin/mihomo")))
    if not binary:
        pytest.skip("mihomo binary is not installed")
    return binary


@pytest.fixture
def all_inbounds(inbounds, certificate):
    hysteria = Inbound.objects.get(kind="hysteria2")
    hysteria.certificate = certificate
    hysteria.enabled = True
    hysteria.save()
    trojan = Inbound.objects.get(kind="trojan")
    trojan.certificate = certificate
    trojan.enabled = True
    # VLESS already owns TCP 443.
    trojan.port = 8444
    trojan.save()
    return inbounds


@pytest.mark.django_db
def test_server_config_contract(singbox, proxy_user, all_inbounds, tmp_path):
    result = generate_config(probe_dns=False)
    path = tmp_path / "server.json"
    write_config(path, result)
    proc = subprocess.run([singbox, "check", "-c", str(path)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(path.read_text())
    assert {block["type"] for block in payload["inbounds"]} == {"vless", "hysteria2", "trojan", "shadowsocks"}


@pytest.mark.django_db
def test_client_singbox_contract(singbox, proxy_user, all_inbounds, tmp_path):
    endpoints = build_endpoints(proxy_user, "vpn.example.com")
    path = tmp_path / "client.json"
    path.write_text(render_singbox(endpoints), encoding="utf-8")
    proc = subprocess.run([singbox, "check", "-c", str(path)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(path.read_text())
    assert [outbound["type"] for outbound in payload["outbounds"][:4]] == [
        "vless",
        "hysteria2",
        "trojan",
        "shadowsocks",
    ]
    assert payload["outbounds"][0]["tls"]["reality"]["public_key"]
    assert payload["outbounds"][1]["tls"]["certificate_public_key_sha256"]
    assert payload["outbounds"][2]["tls"]["certificate_public_key_sha256"]


@pytest.mark.django_db
def test_clash_contract(mihomo, proxy_user, all_inbounds, tmp_path):
    endpoints = build_endpoints(proxy_user, "vpn.example.com")
    path = tmp_path / "config.yaml"
    path.write_text(render_clash(endpoints), encoding="utf-8")
    geo_dir = Path(".cache/mihomo")
    args = [mihomo, "-t", "-f", str(path)]
    if (geo_dir / "geoip.metadb").is_file():
        args[1:1] = ["-d", str(geo_dir)]
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
