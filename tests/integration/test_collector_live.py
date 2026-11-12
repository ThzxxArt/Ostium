from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from ostium.config import Role, Settings
from ostium.core.app import create_core_app
from ostium.db.models import ProxyUser
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.domain.endpoints import Endpoint, Protocol, TLSConfig
from ostium.engine.singbox.config import (
    ClientConfigSpec,
    RealitySpec,
    ServerConfigSpec,
    ServerInbound,
    UserCredential,
    build_client_config,
    build_server_config,
    config_digest,
)
from ostium.engine.singbox.v2ray_stats import V2RayStatsClient
from ostium.services.crypto import SecretStore
from ostium.services.events import EventBus
from ostium.services.stats import StatsCollector
from ostium.services.users import create_user

CUSTOM_CORE = Path(os.environ.get("OSTIUM_TEST_CUSTOM_ENGINE", "/tmp/opencode/sing-box-v2ray"))
OFFICIAL_CORE = Path(os.environ.get("OSTIUM_TEST_ENGINE", "/tmp/opencode/sing-box"))


def _wait_port(port: int, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.05)
    return False


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"ostium-live-collector" * 64
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


@pytest.mark.integration
def test_live_custom_core_collector_accounts_traffic(tmp_path: Path) -> None:
    assert CUSTOM_CORE.is_file(), f"custom core not found at {CUSTOM_CORE}"
    assert OFFICIAL_CORE.is_file(), f"official core not found at {OFFICIAL_CORE}"

    data = tmp_path / "data"
    settings = Settings(
        role=Role.SERVER,
        data_dir=data,
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=data / "runtime" / "core.token",
        engine_path=str(CUSTOM_CORE),
        proxy_ports=[24443],
        dev=True,
        log_level="warning",
    )
    settings.paths.ensure()

    http_server = ThreadingHTTPServer(("127.0.0.1", 28080), _Handler)
    http_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    http_thread.start()

    client_process: subprocess.Popen[bytes] | None = None

    try:

        async def seed() -> tuple[str, str, str]:
            engine = create_engine(settings.paths.db_path)
            try:
                await create_schema(engine)
                factory = create_session_factory(engine)
                store = SecretStore.from_data_dir(settings.data_dir)
                async with factory() as session:
                    user, _password, _token = await create_user(session, store, name="alice")
                    await session.commit()
                    assert isinstance(user, ProxyUser)
                    return user.uuid, user.name, user.id
            finally:
                await engine.dispose()

        uuid, username, user_id = asyncio.run(seed())

        private_key = X25519PrivateKey.generate()
        private_raw = private_key.private_bytes_raw()
        public_raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        reality_private = base64.urlsafe_b64encode(private_raw).decode().rstrip("=")
        reality_public = base64.urlsafe_b64encode(public_raw).decode().rstrip("=")

        server_config = build_server_config(
            ServerConfigSpec(
                inbounds=[
                    ServerInbound(
                        kind="vless",
                        enabled=True,
                        listen="127.0.0.1",
                        port=24443,
                        reality=RealitySpec(
                            private_key=reality_private,
                            short_id="55e1651e",
                            server_name="www.apple.com",
                        ),
                    )
                ],
                users=[
                    UserCredential(
                        name=username,
                        uuid=uuid,
                        password="unused",
                        ss_password="dW51c2Vk",
                    )
                ],
                clash_secret="live-test",
                clash_listen="127.0.0.1:29090",
                v2ray_listen="127.0.0.1:29091",
                block_private_egress=False,
            )
        )

        app = create_core_app(settings)
        with TestClient(app) as core_client:
            token = settings.paths.core_token_path.read_text().strip()
            headers = {"Authorization": f"Bearer {token}"}
            applied = core_client.post(
                "/v1/apply",
                json={
                    "config": server_config,
                    "sha256": config_digest(server_config),
                    "role": "server",
                },
                headers=headers,
            )
            assert applied.status_code == 200, applied.text
            assert _wait_port(24443), "server inbound did not listen"

            endpoint = Endpoint(
                tag="live",
                protocol=Protocol.VLESS_REALITY,
                name="live",
                server="127.0.0.1",
                port=24443,
                uuid=uuid,
                tls=TLSConfig(
                    server_name="www.apple.com",
                    reality_public_key=reality_public,
                    reality_short_id="55e1651e",
                ),
            )
            client_config = build_client_config(
                ClientConfigSpec(
                    endpoints=[endpoint],
                    mixed_port=27890,
                    mode="mixed",
                    clash_secret="live-client",
                    clash_listen="127.0.0.1:29092",
                    log_level="debug",
                )
            )
            # Local test traffic must traverse the proxy rather than being
            # short-circuited by the private-IP direct rule.
            client_config["route"]["rules"] = [
                rule for rule in client_config["route"]["rules"] if not rule.get("ip_is_private")
            ]
            client_config_path = tmp_path / "client.json"
            client_config_path.write_text(json.dumps(client_config))
            client_log_path = tmp_path / "client.log"
            client_log = client_log_path.open("wb")
            client_process = subprocess.Popen(
                [str(OFFICIAL_CORE), "run", "-c", str(client_config_path)],
                stdout=client_log,
                stderr=subprocess.STDOUT,
            )
            assert _wait_port(27890), "client mixed inbound did not listen"

            def curl_once() -> None:
                completed = subprocess.run(
                    [
                        "curl",
                        "-sS",
                        "--max-time",
                        "8",
                        "--noproxy",
                        "",
                        "--socks5-hostname",
                        "127.0.0.1:27890",
                        "http://127.0.0.1:28080/",
                    ],
                    capture_output=True,
                    timeout=15,
                )
                assert completed.returncode == 0, completed.stderr
                assert b"ostium-live-collector" in completed.stdout, completed.stdout

            async def collect_live_traffic() -> int:
                engine = create_engine(settings.paths.db_path)
                collector = StatsCollector(
                    settings=settings,
                    session_factory=create_session_factory(engine),
                    bus=EventBus(),
                    interval=0.05,
                )
                collector.client = V2RayStatsClient("127.0.0.1:29091")
                try:
                    await collector.tick()
                    for _ in range(3):
                        await asyncio.to_thread(curl_once)
                    await asyncio.sleep(1.5)
                    counts = await collector.client.query_users()
                    # Ensure at least one delta is observed regardless of
                    # whether the first sample was a pre-traffic baseline.
                    await collector.tick()
                    await asyncio.to_thread(curl_once)
                    await asyncio.sleep(0.3)
                    await collector.tick()
                    await asyncio.sleep(0.2)
                    await collector.tick()
                    await collector.flush()
                    async with collector.session_factory() as session:
                        user = await session.get(ProxyUser, user_id)
                        used = int(user.used_bytes if user else 0)
                    assert counts, (
                        f"V2Ray API returned no user counters: {counts!r}; "
                        f"route={client_config['route']!r}; "
                        f"log={client_log_path.read_text(errors='replace')[-4000:]}"
                    )
                    assert collector.usage, (
                        f"no live usage snapshot was recorded: counts={counts!r} "
                        f"client_log={client_log_path.read_text(errors='replace')[-2000:]}"
                    )
                    _ = client_log_path
                    return used
                finally:
                    await collector.stop()
                    await engine.dispose()

            used = asyncio.run(collect_live_traffic())
            assert used > 0, "the collector did not account proxied traffic"
    finally:
        if client_process is not None:
            client_process.terminate()
            try:
                client_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                client_process.kill()
        http_server.shutdown()
        http_server.server_close()
        http_thread.join(timeout=5)
