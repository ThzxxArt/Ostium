from __future__ import annotations

import json

import pytest

from ostium.config import Settings
from ostium.system.proxy import BaseProxy, ProxyError, env_hint


def test_base_proxy_status_and_env(settings: Settings) -> None:
    proxy = BaseProxy(settings)
    assert proxy.supported is False
    status = proxy.status()
    assert status["supported"] is False
    assert status["enabled"] is False
    with pytest.raises(ProxyError):
        proxy.enable()
    assert "http_proxy=http://127.0.0.1:7890" in env_hint(7890)


def test_base_proxy_restores_stale_state(settings: Settings) -> None:
    proxy = BaseProxy(settings)
    proxy.state_path.write_text(json.dumps({"system_proxy": {"enabled": True, "platform": "test"}}))
    proxy.recover_if_stale()
    state = json.loads(proxy.state_path.read_text())
    assert state["system_proxy"]["enabled"] is False
