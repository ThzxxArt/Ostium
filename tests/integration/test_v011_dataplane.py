from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest

from ostium.config import Role, Settings
from ostium.engine.singbox.config import (
    SERVER_EGRESS_BLOCK_CIDRS,
    ServerConfigSpec,
    ServerInbound,
    UserCredential,
    build_server_config,
    config_digest,
)
from ostium.engine.singbox.supervisor import CoreSupervisor, EngineCheckFailed
from ostium.engine.singbox.validate import validate_config

pytestmark = pytest.mark.integration


def _engine() -> Path:
    candidates = [
        Path(os.environ.get("OSTIUM_TEST_ENGINE", "")),
        Path("/tmp/opencode/ostium-test/sing-box"),
        Path("/usr/local/bin/sing-box"),
        Path("/usr/bin/sing-box"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    pytest.skip("a real sing-box binary is required")


def _key() -> str:
    return base64.b64encode(os.urandom(16)).decode()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _settings(tmp_path: Path) -> Settings:
    value = Settings(
        role=Role.SERVER,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
        engine_path=str(_engine()),
        proxy_ports=[443, 8388, 18080],
        dev=True,
        log_level="warning",
    )
    value.paths.ensure()
    return value


def test_server_egress_acl_and_real_singbox_check(tmp_path: Path) -> None:
    engine = _engine()
    config = build_server_config(
        ServerConfigSpec(
            inbounds=[
                ServerInbound(
                    kind="shadowsocks",
                    enabled=True,
                    listen="127.0.0.1",
                    port=18080,
                    ss_server_key=_key(),
                )
            ],
            users=[
                UserCredential(
                    name="alice",
                    uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
                    password="pw",
                    ss_password=_key(),
                )
            ],
            clash_secret="test-secret",
            enable_v2ray_api=False,
        )
    )
    validate_config(
        config,
        role=Role.SERVER,
        allowed_ports={18080},
        allowed_paths=[tmp_path],
    )
    (tmp_path / "server.json").write_text(json.dumps(config))
    assert {"10.0.0.0/8", "100.64.0.0/10", "169.254.0.0/16"}.issubset(
        set(SERVER_EGRESS_BLOCK_CIDRS)
    )
    assert config["route"]["rules"][0]["action"] == "reject"
    assert "169.254.169.254/32" in config["route"]["rules"][0]["ip_cidr"]
    assert {"action": "reject", "port": [25]} in config["route"]["rules"]
    check = subprocess.run(
        [str(engine), "check", "-c", str(tmp_path / "server.json")],
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stderr


def test_ss2022_multiuser_loopback_traffic(tmp_path: Path) -> None:
    engine = _engine()
    server_port = _free_port()
    client_port = _free_port()
    http_port = _free_port()
    server_key = _key()
    user_key = _key()
    server_config = {
        "log": {"level": "warning"},
        "inbounds": [
            {
                "type": "shadowsocks",
                "tag": "ss-in",
                "listen": "127.0.0.1",
                "listen_port": server_port,
                "method": "2022-blake3-aes-128-gcm",
                "password": server_key,
                "users": [{"name": "alice", "password": user_key}],
            }
        ],
        "outbounds": [{"type": "direct", "tag": "direct"}],
        "route": {"final": "direct"},
    }
    client_config = {
        "log": {"level": "warning"},
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": client_port,
            }
        ],
        "outbounds": [
            {
                "type": "shadowsocks",
                "tag": "ss-out",
                "server": "127.0.0.1",
                "server_port": server_port,
                "method": "2022-blake3-aes-128-gcm",
                "password": f"{server_key}:{user_key}",
            },
            {"type": "direct", "tag": "direct"},
        ],
        "route": {"final": "ss-out"},
    }
    server_path = tmp_path / "ss-server.json"
    client_path = tmp_path / "ss-client.json"
    server_path.write_text(json.dumps(server_config))
    client_path.write_text(json.dumps(client_config))
    http_root = tmp_path / "http"
    http_root.mkdir()
    (http_root / "probe.txt").write_text("ostium-ss2022-ok")

    processes: list[subprocess.Popen[str]] = []
    try:
        processes.append(
            subprocess.Popen(
                [str(engine), "run", "-c", str(server_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
        processes.append(
            subprocess.Popen(
                [str(engine), "run", "-c", str(client_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
        http = subprocess.Popen(
            ["python3", "-m", "http.server", str(http_port), "--bind", "127.0.0.1"],
            cwd=http_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        processes.append(http)
        time.sleep(1.2)
        for process in processes[:2]:
            assert process.poll() is None, process.stderr.read() if process.stderr else ""
        result = subprocess.run(
            [
                "curl",
                "-fsS",
                "--max-time",
                "10",
                "--noproxy",
                "",
                "-x",
                f"socks5h://127.0.0.1:{client_port}",
                f"http://127.0.0.1:{http_port}/probe.txt",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "ostium-ss2022-ok"
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def test_apply_failure_keeps_previous_configuration(tmp_path: Path) -> None:
    import asyncio

    async def _run() -> None:
        engine_path = _engine()
        settings = _settings(tmp_path)
        supervisor = CoreSupervisor(settings)
        spec = ServerConfigSpec(
            inbounds=[
                ServerInbound(
                    kind="shadowsocks",
                    enabled=True,
                    listen="127.0.0.1",
                    port=18080,
                    ss_server_key=_key(),
                )
            ],
            users=[
                UserCredential(
                    name="alice",
                    uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
                    password="pw",
                    ss_password=_key(),
                )
            ],
            clash_secret="secret",
            enable_v2ray_api=False,
        )
        good = build_server_config(spec)
        try:
            await supervisor.apply(good, config_digest(good))
            assert supervisor.status().running
            previous = supervisor.last_good.read_bytes()

            bad = json.loads(json.dumps(good))
            bad["inbounds"][0]["method"] = "not-a-real-method"
            with pytest.raises(EngineCheckFailed):
                await supervisor.apply(bad, config_digest(bad))
            assert supervisor.last_good.read_bytes() == previous
            assert supervisor.status().running
        finally:
            await supervisor.shutdown()

        assert engine_path.is_file()

    asyncio.run(_run())
