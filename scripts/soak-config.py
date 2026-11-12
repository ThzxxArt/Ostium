#!/usr/bin/env python3
"""Bounded config-generation soak used by the nightly workflow.

This is not a 72-hour traffic soak; it repeatedly builds and validates the
client config to catch generator/validator regressions and file-handle leaks.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from ostium.domain.endpoints import Endpoint, Protocol, TLSConfig
from ostium.engine.singbox.config import ClientConfigSpec, build_client_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--mixed-port", type=int, default=27890)
    args = parser.parse_args()

    endpoint = Endpoint(
        tag="soak",
        protocol=Protocol.VLESS_REALITY,
        name="soak",
        server="vpn.example.com",
        port=443,
        uuid="2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e",
        tls=TLSConfig(
            server_name="www.apple.com",
            reality_public_key="Bs2KLXAKuw5pGFpBIwnyt896Y8mhNJHewMHHY0en6hM",
            reality_short_id="55e1651e",
        ),
    )
    with tempfile.TemporaryDirectory(prefix="ostium-soak-") as temp:
        config_path = Path(temp) / "client.json"
        for index in range(args.iterations):
            spec = ClientConfigSpec(
                endpoints=[endpoint],
                mixed_port=args.mixed_port,
                allow_lan=index % 2 == 0,
                clash_secret=f"soak-{index}",
            )
            config_path.write_text(
                json.dumps(build_client_config(spec), ensure_ascii=False), encoding="utf-8"
            )
            result = subprocess.run(
                [str(args.engine), "check", "-c", str(config_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                print(result.stdout)
                print(result.stderr)
                return result.returncode
    print(f"validated {args.iterations} generated client configs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
