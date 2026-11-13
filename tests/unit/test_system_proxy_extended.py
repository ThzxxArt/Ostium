from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from ostium.config import Settings
from ostium.system import proxy as proxy_module
from ostium.system.proxy import (
    BaseProxy,
    GnomeProxy,
    KdeProxy,
    MacProxy,
    ProxyError,
    WindowsProxy,
    _read_state,
    _run,
    _write_state,
    env_hint,
    system_proxy,
)


class Result:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _patch_run(monkeypatch: pytest.MonkeyPatch, responses: Any) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(command: list[str], timeout: float = 15.0) -> Result:
        calls.append(command)
        if callable(responses):
            return responses(command)
        return responses

    monkeypatch.setattr(proxy_module, "_run", fake_run)
    return calls


def test_run_wraps_os_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_args: Any, **_kwargs: Any) -> Any:
        raise FileNotFoundError("missing")

    monkeypatch.setattr(proxy_module.subprocess, "run", missing)
    with pytest.raises(ProxyError, match="required command not found"):
        _run(["nope"])

    def timeout(*_args: Any, **_kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(["slow"], 1)

    monkeypatch.setattr(proxy_module.subprocess, "run", timeout)
    with pytest.raises(ProxyError, match="timed out"):
        _run(["slow"])

    monkeypatch.setattr(
        proxy_module.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "ok", ""),
    )
    assert _run(["echo"]).stdout == "ok"


def test_state_helpers(tmp_path: Path) -> None:
    assert _read_state(tmp_path / "none") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    assert _read_state(bad) == {}
    target = tmp_path / "nested" / "state.json"
    _write_state(target, {"system_proxy": {"enabled": True}})
    assert json.loads(target.read_text())["system_proxy"]["enabled"] is True


def test_base_proxy(settings: Settings) -> None:
    base = BaseProxy(settings)
    assert base.supported is False
    status = base.status()
    assert status["platform"] == "unsupported"
    assert status["enabled"] is False
    with pytest.raises(ProxyError):
        base.enable()

    state = {proxy_module.STATE_KEY: {"enabled": True, "clean_shutdown": False}}
    _write_state(base.state_path, state)
    base.recover_if_stale()
    assert json.loads(base.state_path.read_text())[proxy_module.STATE_KEY]["enabled"] is False

    state = {proxy_module.STATE_KEY: {"enabled": True, "clean_shutdown": True}}
    _write_state(base.state_path, state)
    base.recover_if_stale()
    assert json.loads(base.state_path.read_text())[proxy_module.STATE_KEY]["enabled"] is True


def test_base_proxy_stale_disable_failure(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = BaseProxy(settings)
    _write_state(base.state_path, {proxy_module.STATE_KEY: {"enabled": True}})
    monkeypatch.setattr(base, "disable", lambda: (_ for _ in ()).throw(ProxyError("no")))
    base.recover_if_stale()  # must not raise


def test_gnome_proxy_enable_disable(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(proxy_module.shutil, "which", lambda name: "/usr/bin/gsettings")
    values = {
        ("org.gnome.system.proxy", "mode"): "'none'",
        ("org.gnome.system.proxy.http", "host"): "old-http",
        ("org.gnome.system.proxy.http", "port"): "8080",
        ("org.gnome.system.proxy.https", "host"): "old-https",
        ("org.gnome.system.proxy.https", "port"): "8443",
        ("org.gnome.system.proxy.socks", "host"): "old-socks",
        ("org.gnome.system.proxy.socks", "port"): "1080",
        ("org.gnome.system.proxy", "ignore-hosts"): "['localhost']",
    }

    def responder(command: list[str]) -> Result:
        if command[1] == "get":
            return Result(stdout=values.get((command[2], command[3]), ""))
        return Result()

    calls = _patch_run(monkeypatch, responder)
    proxy = GnomeProxy(settings)
    assert proxy.supported is True
    status = proxy.enable(port=7890)
    assert status["enabled"] is True
    assert status["platform"] == "linux-gnome"
    assert any(command[1] == "set" for command in calls)

    calls.clear()
    status = proxy.disable()
    assert status["enabled"] is False
    assert ["gsettings", "set", "org.gnome.system.proxy", "mode", "'none'"] in calls


def test_gnome_proxy_schema_missing_and_errors(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(proxy_module.shutil, "which", lambda name: None)
    assert GnomeProxy(settings).supported is False

    monkeypatch.setattr(proxy_module.shutil, "which", lambda name: "/usr/bin/gsettings")
    _patch_run(monkeypatch, Result(returncode=1, stderr="no schema"))
    proxy = GnomeProxy(settings)
    assert proxy.supported is False
    with pytest.raises(ProxyError, match="no schema"):
        proxy._get("schema", "key")
    with pytest.raises(ProxyError, match="no schema"):
        proxy._set("schema", "key", "value")

    _patch_run(monkeypatch, Result(returncode=1))
    with pytest.raises(ProxyError):
        proxy.enable()


def test_gnome_partial_failure_restores_original_state(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def responder(command: list[str]) -> Result:
        calls.append(command)
        if len(command) > 3 and command[1] == "set" and command[3] == "port":
            return Result(returncode=1, stderr="port write failed")
        if command[1] == "get":
            return Result(stdout="'original'")
        return Result()

    _patch_run(monkeypatch, responder)
    proxy = GnomeProxy(settings)
    with pytest.raises(ProxyError, match="port write failed"):
        proxy.enable(port=7893)
    assert any(call[-2:] == ["mode", "'original'"] for call in calls)
    # The restore itself could not complete (the failing key is retried by
    # disable), so the state must stay dirty.  Marking it clean would hide a
    # partially applied proxy from the next startup recovery.
    entry = _read_state(proxy.state_path)[proxy_module.STATE_KEY]
    assert entry["enabled"] is True
    assert entry["clean_shutdown"] is False


def test_gnome_disable_without_original(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _patch_run(monkeypatch, Result())
    proxy = GnomeProxy(settings)
    proxy.disable()
    assert ["gsettings", "set", "org.gnome.system.proxy", "mode", "'none'"] in calls


def test_kde_proxy(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(proxy_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = _patch_run(monkeypatch, Result())
    proxy = KdeProxy(settings)
    assert proxy.supported is True
    status = proxy.enable(port=7891)
    assert status["enabled"] is True
    status = proxy.disable()
    assert status["enabled"] is False
    assert any("ProxyType" in call for call in calls if len(call) > 1)

    monkeypatch.setattr(proxy_module.shutil, "which", lambda name: None)
    assert proxy.supported is False
    with pytest.raises(ProxyError, match="not available"):
        proxy._write("ProxyType", "1")

    monkeypatch.setattr(proxy_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    _patch_run(monkeypatch, Result(returncode=1, stderr="bad"))
    with pytest.raises(ProxyError, match="bad"):
        proxy._write("ProxyType", "1")


def test_kde_restores_missing_original_keys(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(proxy_module.shutil, "which", lambda name: f"/usr/bin/{name}")

    def responder(command: list[str]) -> Result:
        if "kreadconfig6" in command[0]:
            return Result(returncode=1)
        return Result()

    calls = _patch_run(monkeypatch, responder)
    proxy = KdeProxy(settings)
    proxy.enable(port=7891)
    proxy.disable()
    assert any("--delete" in call for call in calls)


def test_kde_without_read_tool_only_disables_proxy_type(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        proxy_module.shutil,
        "which",
        lambda name: "/usr/bin/kwriteconfig6" if name == "kwriteconfig6" else None,
    )
    calls = _patch_run(monkeypatch, Result())
    proxy = KdeProxy(settings)
    proxy.enable(port=7891)
    proxy.disable()
    assert any(call[-2:] == ["ProxyType", "0"] for call in calls)
    assert not any("--delete" in call for call in calls)


def test_kde_write_failure_and_no_dbus(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        proxy_module.shutil,
        "which",
        lambda name: "/usr/bin/kwriteconfig6" if name == "kwriteconfig6" else None,
    )
    _patch_run(monkeypatch, Result(returncode=2, stderr="nope"))
    with pytest.raises(ProxyError):
        KdeProxy(settings).enable()
    _patch_run(monkeypatch, Result())
    KdeProxy(settings)._notify()


def test_mac_proxy_services_and_enable_disable(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(proxy_module.sys, "platform", "darwin")
    monkeypatch.setattr(proxy_module.shutil, "which", lambda name: "/usr/sbin/networksetup")

    def responder(command: list[str]) -> Result:
        if command[1] == "-listallnetworkservices":
            return Result(stdout="An asterisk denotes disabled\n*Thunderbolt\nWi-Fi\n\n")
        if command[1] in {"-getwebproxy", "-getsecurewebproxy", "-getsocksfirewallproxy"}:
            return Result(
                stdout="Enabled: Yes\nServer: 10.0.0.2\nPort: 8080\n"
                if command[1] == "-getwebproxy"
                else "Enabled: No\nServer: \nPort: unknown\n"
            )
        return Result()

    calls = _patch_run(monkeypatch, responder)
    proxy = MacProxy(settings)
    assert proxy.supported is True
    assert proxy._services() == ["Wi-Fi"]
    status = proxy.enable(port=7892)
    assert status["enabled"] is True
    assert any(call[1] == "-setwebproxy" for call in calls)

    calls.clear()
    status = proxy.disable()
    assert status["enabled"] is False
    assert any(call[1] == "-setwebproxy" for call in calls)
    assert any(call[1] == "-setsecurewebproxystate" for call in calls)
    assert any(call[1] == "-setsocksfirewallproxystate" for call in calls)

    monkeypatch.setattr(proxy_module.sys, "platform", "linux")
    assert MacProxy(settings).supported is False


def test_mac_disable_without_state(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_run(monkeypatch, Result())
    proxy = MacProxy(settings)
    proxy.disable()
    assert calls == []


class _FakeKey:
    def __init__(self, store: dict[str, Any], fail_names: set[str]) -> None:
        self.store = store
        self.fail_names = fail_names

    def __enter__(self) -> _FakeKey:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


def _fake_winreg(store: dict[str, Any], fail_names: set[str] | None = None) -> types.ModuleType:
    module = types.ModuleType("winreg")
    module.HKEY_CURRENT_USER = object()
    module.KEY_READ = 1
    module.KEY_WRITE = 2
    module.REG_DWORD = 4
    module.REG_SZ = 1
    failures = fail_names or set()

    def open_key(*_args: Any) -> _FakeKey:
        return _FakeKey(store, failures)

    def query_value(key: _FakeKey, name: str) -> tuple[Any, int]:
        if name not in key.store:
            raise FileNotFoundError(name)
        return key.store[name], 1

    def set_value(key: _FakeKey, name: str, _reserved: int, _kind: int, value: Any) -> None:
        key.store[name] = value

    def delete_value(key: _FakeKey, name: str) -> None:
        if name not in key.store:
            raise FileNotFoundError(name)
        del key.store[name]

    module.OpenKey = open_key  # type: ignore[attr-defined]
    module.QueryValueEx = query_value  # type: ignore[attr-defined]
    module.SetValueEx = set_value  # type: ignore[attr-defined]
    module.DeleteValue = delete_value  # type: ignore[attr-defined]
    return module


def test_windows_proxy(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, Any] = {
        "ProxyEnable": 0,
        "ProxyServer": "old:1",
        "AutoConfigURL": "http://pac.example/proxy.pac",
    }
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(store))
    monkeypatch.setattr(proxy_module, "_notify_wininet", lambda: None)
    monkeypatch.setattr(proxy_module.sys, "platform", "win32")
    proxy = WindowsProxy(settings)
    assert proxy.supported is True
    status = proxy.enable(port=7893)
    assert status["enabled"] is True
    assert store["ProxyEnable"] == 1
    assert store["ProxyServer"] == "127.0.0.1:7893"
    assert "AutoConfigURL" not in store

    status = proxy.disable()
    assert status["enabled"] is False
    assert store["ProxyEnable"] == 0
    assert store["ProxyServer"] == "old:1"
    assert store["AutoConfigURL"] == "http://pac.example/proxy.pac"

    # Missing originals are created as disabled/empty values.
    proxy.state_path.unlink()
    store.clear()
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(store))
    proxy.disable()
    assert store["ProxyEnable"] == 0
    assert "ProxyServer" not in store
    assert "AutoConfigURL" not in store

    monkeypatch.setattr(proxy_module.sys, "platform", "linux")
    assert WindowsProxy(settings).supported is False


def test_windows_proxy_removes_values_it_created(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    store: dict[str, Any] = {}
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(store))
    monkeypatch.setattr(proxy_module, "_notify_wininet", lambda: None)
    monkeypatch.setattr(proxy_module.sys, "platform", "win32")
    proxy = WindowsProxy(settings)
    proxy.enable(port=7894)
    assert store["ProxyServer"] == "127.0.0.1:7894"
    assert "ProxyOverride" in store
    proxy.disable()
    assert store["ProxyEnable"] == 0
    assert "ProxyServer" not in store
    assert "ProxyOverride" not in store
    assert "AutoConfigURL" not in store


def test_system_proxy_factory(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(proxy_module.sys, "platform", "win32")
    assert isinstance(system_proxy(settings), WindowsProxy)
    monkeypatch.setattr(proxy_module.sys, "platform", "darwin")
    assert isinstance(system_proxy(settings), MacProxy)
    monkeypatch.setattr(proxy_module.sys, "platform", "linux")
    monkeypatch.setattr(GnomeProxy, "supported", property(lambda self: True))
    assert isinstance(system_proxy(settings), GnomeProxy)
    monkeypatch.setattr(GnomeProxy, "supported", property(lambda self: False))
    monkeypatch.setattr(KdeProxy, "supported", property(lambda self: True))
    assert isinstance(system_proxy(settings), KdeProxy)
    monkeypatch.setattr(KdeProxy, "supported", property(lambda self: False))
    assert isinstance(system_proxy(settings), BaseProxy)


def test_env_hint() -> None:
    hint = env_hint(7890)
    assert "http://127.0.0.1:7890" in hint
    assert "socks5://127.0.0.1:7890" in hint
