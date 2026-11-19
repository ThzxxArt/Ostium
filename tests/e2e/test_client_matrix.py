"""Real-client E2E matrix.

Run with::

    OSTIUM_E2E=1 uv run pytest tests/e2e/test_client_matrix.py -q

The harness starts a local sing-box server on high ports, a local TLS target
for the VLESS Reality handshake, and real Mihomo / sing-box / Xray clients.
It needs outbound internet access for the final HTTP probe.
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import socket
import ssl
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import yaml

from ostium.certificates.services import generate_self_signed
from ostium.engine.config import generate_config, write_config
from ostium.proxy.services import create_proxy_user, initialize_inbounds
from ostium.subscriptions.endpoints import build_endpoints
from ostium.subscriptions.renderers import render_clash, render_singbox

pytestmark = pytest.mark.e2e

TARGET = "https://example.com"
CURL = shutil.which("curl") or "/usr/bin/curl"


def _free_port(sock_type: int) -> int:
    with socket.socket(socket.AF_INET, sock_type) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _binary(name: str, env: str | None = None) -> str | None:
    if env and os.environ.get(env):
        path = Path(os.environ[env])
        if path.is_file():
            return str(path.resolve())
    found = shutil.which(name)
    if found:
        return str(Path(found).resolve())
    for candidate in (Path(".cache/bin") / name, Path("/tmp/opencode/xray") / name):
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def _wait_tcp(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise AssertionError(f"port {port} did not open")


def _curl(port: int, *, socks: bool = False) -> tuple[int, str]:
    proxy = f"socks5h://127.0.0.1:{port}" if socks else f"http://127.0.0.1:{port}"
    proc = subprocess.run(
        [
            CURL,
            "--noproxy",
            "",
            "-sS",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "25",
            "--proxy",
            proxy,
            TARGET,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return int(proc.stdout.strip() or 0), proc.stderr.strip()


def _start(command: list[str], log_path: Path, cwd: Path) -> subprocess.Popen:
    cwd.mkdir(parents=True, exist_ok=True)
    log = log_path.open("wb")
    process = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    process._ostium_log = log  # type: ignore[attr-defined]
    return process


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    log = getattr(process, "_ostium_log", None)
    if log:
        log.close()


class _TLSHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ostium-e2e")

    def log_message(self, *_args):
        return


@pytest.fixture
def e2e_server(db, settings, tmp_path):
    if os.environ.get("OSTIUM_E2E") != "1":
        pytest.skip("set OSTIUM_E2E=1 and install sing-box/mihomo binaries")

    singbox = _binary("sing-box", "OSTIUM_SINGBOX_PATH")
    if not singbox:
        pytest.skip("sing-box binary is not installed")

    tls_port = _free_port(socket.SOCK_STREAM)
    certificate = generate_self_signed("localhost")
    handler = _TLSHandler
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", tls_port), handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate.cert_file, certificate.key_file)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    inbounds = initialize_inbounds(enable=("vless", "hysteria2", "trojan", "shadowsocks"))
    by_kind = {item.kind: item for item in inbounds}
    by_kind["vless"].port = _free_port(socket.SOCK_STREAM)
    by_kind["vless"].update_params(
        server_name="localhost",
        handshake_server="127.0.0.1",
        handshake_port=tls_port,
    )
    by_kind["vless"].save()
    by_kind["hysteria2"].port = _free_port(socket.SOCK_DGRAM)
    by_kind["hysteria2"].certificate = certificate
    by_kind["hysteria2"].save()
    by_kind["trojan"].port = _free_port(socket.SOCK_STREAM)
    by_kind["trojan"].certificate = certificate
    by_kind["trojan"].save()
    by_kind["shadowsocks"].port = _free_port(socket.SOCK_STREAM)
    by_kind["shadowsocks"].save()

    from constance import config as runtime_config

    runtime_config.server_dns_mode = "udp"
    settings.OSTIUM_SINGBOX_CLASH_BIND = f"127.0.0.1:{_free_port(socket.SOCK_STREAM)}"
    settings.OSTIUM_SINGBOX_STATS_ADDRESS = f"127.0.0.1:{_free_port(socket.SOCK_STREAM)}"
    user, _token = create_proxy_user("e2e", quota_bytes=0)
    config_path = tmp_path / "server.json"
    write_config(config_path, generate_config(probe_dns=False))

    server = _start(
        [singbox, "-D", str(tmp_path / "server-data"), "run", "-c", str(config_path)],
        tmp_path / "server.log",
        tmp_path,
    )
    try:
        _wait_tcp(by_kind["vless"].port)
        endpoints = build_endpoints(user, "127.0.0.1")
        yield {
            "tmp": tmp_path,
            "endpoints": endpoints,
            "ports": {kind: item.port for kind, item in by_kind.items()},
            "mihomo": _binary("mihomo"),
            "singbox": singbox,
            "xray": _binary("xray", "OSTIUM_XRAY_PATH"),
        }
    finally:
        _stop(server)
        httpd.shutdown()
        httpd.server_close()


def test_real_client_matrix(e2e_server):
    endpoints = e2e_server["endpoints"]
    assert len(endpoints) == 4
    tmp = e2e_server["tmp"]

    # Mihomo: select each generated proxy through the Clash API.
    if e2e_server["mihomo"]:
        port = _free_port(socket.SOCK_STREAM)
        controller = _free_port(socket.SOCK_STREAM)
        profile = yaml.safe_load(render_clash(endpoints))
        profile["mixed-port"] = port
        profile["external-controller"] = f"127.0.0.1:{controller}"
        profile["secret"] = "e2e"
        profile_path = tmp / "mihomo.yaml"
        profile_path.write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8")
        process = _start(
            [e2e_server["mihomo"], "-d", str(tmp / "mihomo-data"), "-f", str(profile_path)],
            tmp / "mihomo.log",
            tmp,
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{controller}/version",
                        headers={"Authorization": "Bearer e2e"},
                    )
                    urllib.request.urlopen(request, timeout=1).read()  # noqa: S310
                    break
                except OSError:
                    time.sleep(0.1)
            for endpoint in endpoints:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{controller}/proxies/Ostium",
                    data=json.dumps({"name": endpoint.name}).encode(),
                    headers={"Authorization": "Bearer e2e", "Content-Type": "application/json"},
                    method="PUT",
                )
                urllib.request.urlopen(request, timeout=2).read()  # noqa: S310
                time.sleep(0.4)
                code, error = _curl(port)
                assert code in {200, 204}, (
                    endpoint.protocol,
                    error,
                    (tmp / "mihomo.log").read_text(),
                )
        finally:
            _stop(process)

    # sing-box: one outbound at a time, so route.final points directly at it.
    for endpoint in endpoints:
        port = _free_port(socket.SOCK_STREAM)
        profile = json.loads(render_singbox(endpoints))
        profile["inbounds"][0]["listen_port"] = port
        profile["route"]["final"] = endpoint.name
        profile_path = tmp / f"singbox-{endpoint.protocol}.json"
        profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        process = _start(
            [e2e_server["singbox"], "-D", str(tmp / f"singbox-{endpoint.protocol}"), "run", "-c", str(profile_path)],
            tmp / f"singbox-{endpoint.protocol}.log",
            tmp,
        )
        try:
            _wait_tcp(port)
            code, error = _curl(port)
            assert code in {200, 204}, (
                endpoint.protocol,
                error,
                (tmp / f"singbox-{endpoint.protocol}.log").read_text(),
            )
        finally:
            _stop(process)

    # Xray: VLESS Reality, Trojan and Shadowsocks. Hysteria2 is sing-box-only.
    if e2e_server["xray"]:
        for endpoint in endpoints:
            if endpoint.protocol == "hysteria2":
                continue
            port = _free_port(socket.SOCK_STREAM)
            outbound = {
                "tag": endpoint.name,
                "protocol": endpoint.protocol,
                "settings": {},
            }
            if endpoint.protocol == "vless":
                outbound["settings"] = {
                    "vnext": [
                        {
                            "address": endpoint.server,
                            "port": endpoint.port,
                            "users": [
                                {
                                    "id": endpoint.uuid,
                                    "encryption": "none",
                                    "flow": endpoint.flow or "xtls-rprx-vision",
                                }
                            ],
                        }
                    ]
                }
                outbound["streamSettings"] = {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "serverName": endpoint.sni or endpoint.server,
                        "fingerprint": "chrome",
                        "publicKey": endpoint.reality_public_key,
                        "shortId": endpoint.reality_short_id or "",
                    },
                }
            elif endpoint.protocol == "trojan":
                outbound["settings"] = {
                    "servers": [
                        {
                            "address": endpoint.server,
                            "port": endpoint.port,
                            "password": endpoint.password,
                        }
                    ]
                }
                outbound["streamSettings"] = {
                    "network": "tcp",
                    "security": "tls",
                    "tlsSettings": {
                        "serverName": endpoint.sni or endpoint.server,
                        "pinnedPeerCertSha256": endpoint.cert_fingerprint,
                    },
                }
            elif endpoint.protocol == "shadowsocks":
                outbound["settings"] = {
                    "servers": [
                        {
                            "address": endpoint.server,
                            "port": endpoint.port,
                            "method": endpoint.method,
                            "password": endpoint.ss_password,
                        }
                    ]
                }
            profile = {
                "log": {"loglevel": "warning"},
                "inbounds": [
                    {
                        "tag": "socks-in",
                        "listen": "127.0.0.1",
                        "port": port,
                        "protocol": "socks",
                        "settings": {"udp": False},
                    }
                ],
                "outbounds": [outbound],
            }
            profile_path = tmp / f"xray-{endpoint.protocol}.json"
            profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
            process = _start(
                [e2e_server["xray"], "run", "-c", str(profile_path)],
                tmp / f"xray-{endpoint.protocol}.log",
                tmp,
            )
            try:
                _wait_tcp(port)
                code, error = _curl(port, socks=True)
                assert code in {200, 204}, (
                    endpoint.protocol,
                    error,
                    (tmp / f"xray-{endpoint.protocol}.log").read_text(),
                )
            finally:
                _stop(process)
