"""Operating-system proxy integration with crash-safe restoration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ostium.config import Settings

STATE_KEY = "system_proxy"


class ProxyError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def _run(command: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ProxyError(f"required command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProxyError(f"command timed out: {command[0]}") from exc


def _read_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    if os.name == "posix":
        path.chmod(0o600)


class BaseProxy:
    platform = "unsupported"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state_path = settings.paths.state_dir / "system-proxy.json"

    @property
    def supported(self) -> bool:
        return False

    def status(self) -> dict[str, Any]:
        state = _read_state(self.state_path).get(STATE_KEY, {})
        return {
            "supported": self.supported,
            "platform": self.platform,
            "enabled": bool(state.get("enabled")),
            "host": state.get("host", "127.0.0.1"),
            "port": state.get("port", self.settings.mixed_port),
        }

    def enable(self, host: str = "127.0.0.1", port: int | None = None) -> dict[str, Any]:
        raise ProxyError(f"system proxy is not supported on this platform ({self.platform})")

    def disable(self) -> dict[str, Any]:
        state = _read_state(self.state_path)
        state.setdefault(STATE_KEY, {})["enabled"] = False
        _write_state(self.state_path, state)
        return self.status()

    def recover_if_stale(self) -> None:
        state = _read_state(self.state_path).get(STATE_KEY, {})
        if state.get("enabled") and not state.get("clean_shutdown", False):
            try:
                self.disable()
            except ProxyError:
                pass


class GnomeProxy(BaseProxy):
    platform = "linux-gnome"

    @property
    def supported(self) -> bool:
        return shutil.which("gsettings") is not None and self._schema_available()

    def _schema_available(self) -> bool:
        result = _run(["gsettings", "get", "org.gnome.system.proxy", "mode"])
        return result.returncode == 0

    def _get(self, schema: str, key: str) -> str:
        result = _run(["gsettings", "get", schema, key])
        if result.returncode != 0:
            raise ProxyError(result.stderr.strip() or f"could not read {schema} {key}")
        return result.stdout.strip()

    def _set(self, schema: str, key: str, value: str) -> None:
        result = _run(["gsettings", "set", schema, key, value])
        if result.returncode != 0:
            raise ProxyError(result.stderr.strip() or f"could not set {schema} {key}")

    def enable(self, host: str = "127.0.0.1", port: int | None = None) -> dict[str, Any]:
        port = port or self.settings.mixed_port
        original = {
            "mode": self._get("org.gnome.system.proxy", "mode"),
            "http_host": self._get("org.gnome.system.proxy.http", "host"),
            "http_port": self._get("org.gnome.system.proxy.http", "port"),
            "https_host": self._get("org.gnome.system.proxy.https", "host"),
            "https_port": self._get("org.gnome.system.proxy.https", "port"),
            "socks_host": self._get("org.gnome.system.proxy.socks", "host"),
            "socks_port": self._get("org.gnome.system.proxy.socks", "port"),
            "ignore_hosts": self._get("org.gnome.system.proxy", "ignore-hosts"),
        }
        self._set("org.gnome.system.proxy.http", "host", host)
        self._set("org.gnome.system.proxy.http", "port", str(port))
        self._set("org.gnome.system.proxy.https", "host", host)
        self._set("org.gnome.system.proxy.https", "port", str(port))
        self._set("org.gnome.system.proxy.socks", "host", host)
        self._set("org.gnome.system.proxy.socks", "port", str(port))
        self._set(
            "org.gnome.system.proxy",
            "ignore-hosts",
            "['localhost', '127.0.0.0/8', '::1', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16']",
        )
        self._set("org.gnome.system.proxy", "mode", "'manual'")
        state = _read_state(self.state_path)
        state[STATE_KEY] = {
            "platform": self.platform,
            "enabled": True,
            "host": host,
            "port": port,
            "original": original,
            "clean_shutdown": False,
        }
        _write_state(self.state_path, state)
        return self.status()

    def disable(self) -> dict[str, Any]:
        state = _read_state(self.state_path)
        entry = state.get(STATE_KEY, {})
        original = entry.get("original") or {}
        if original:
            for key, value in original.items():
                schema, _, name = key.partition("_")
                if key == "mode":
                    self._set("org.gnome.system.proxy", "mode", value)
                elif key == "ignore_hosts":
                    self._set("org.gnome.system.proxy", "ignore-hosts", value)
                else:
                    self._set(f"org.gnome.system.proxy.{schema}", name, value)
        else:
            self._set("org.gnome.system.proxy", "mode", "'none'")
        entry.update({"enabled": False, "clean_shutdown": True})
        state[STATE_KEY] = entry
        _write_state(self.state_path, state)
        return self.status()


class KdeProxy(BaseProxy):
    platform = "linux-kde"

    @property
    def supported(self) -> bool:
        return (
            shutil.which("kwriteconfig6") is not None or shutil.which("kwriteconfig5") is not None
        )

    @property
    def _can_read(self) -> bool:
        return shutil.which("kreadconfig6") is not None or shutil.which("kreadconfig5") is not None

    def _read(self, key: str) -> str | None:
        command = shutil.which("kreadconfig6") or shutil.which("kreadconfig5")
        if not command:
            return None
        result = _run([command, "--file", "kioslaverc", "--group", "Proxy Settings", "--key", key])
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def _delete(self, key: str) -> None:
        command = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
        if not command:
            raise ProxyError("kwriteconfig is not available")
        result = _run(
            [
                command,
                "--file",
                "kioslaverc",
                "--group",
                "Proxy Settings",
                "--key",
                key,
                "--delete",
            ]
        )
        if result.returncode != 0:
            raise ProxyError(result.stderr.strip() or f"could not restore KDE proxy {key}")

    def _write(self, key: str, value: str) -> None:
        command = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
        if not command:
            raise ProxyError("kwriteconfig is not available")
        result = _run(
            [command, "--file", "kioslaverc", "--group", "Proxy Settings", "--key", key, value]
        )
        if result.returncode != 0:
            raise ProxyError(result.stderr.strip() or f"could not set KDE proxy {key}")

    def enable(self, host: str = "127.0.0.1", port: int | None = None) -> dict[str, Any]:
        port = port or self.settings.mixed_port
        keys = ("ProxyType", "httpProxy", "httpsProxy", "socksProxy", "NoProxyFor")
        original = {key: self._read(key) for key in keys} if self._can_read else {}
        self._write("ProxyType", "1")
        self._write("httpProxy", f"http://{host} {port}")
        self._write("httpsProxy", f"http://{host} {port}")
        self._write("socksProxy", f"socks://{host} {port}")
        self._write("NoProxyFor", "localhost,127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16")
        self._notify()
        state = _read_state(self.state_path)
        state[STATE_KEY] = {
            "platform": self.platform,
            "enabled": True,
            "host": host,
            "port": port,
            "original": original,
            "clean_shutdown": False,
        }
        _write_state(self.state_path, state)
        return self.status()

    def disable(self) -> dict[str, Any]:
        state = _read_state(self.state_path)
        entry = state.get(STATE_KEY, {})
        original = entry.get("original") or {}
        if original:
            for key, value in original.items():
                if value is None:
                    self._delete(key)
                else:
                    self._write(key, value)
        else:
            self._write("ProxyType", "0")
        self._notify()
        entry.update({"enabled": False, "clean_shutdown": True})
        state[STATE_KEY] = entry
        _write_state(self.state_path, state)
        return self.status()

    def _notify(self) -> None:
        if shutil.which("dbus-send"):
            _run(
                [
                    "dbus-send",
                    "--type=signal",
                    "/KIO/Scheduler",
                    "org.kde.KIO.Scheduler.reparseSlaveConfiguration",
                    "string:",
                ]
            )


class MacProxy(BaseProxy):
    platform = "macos"

    @property
    def supported(self) -> bool:
        return sys.platform == "darwin" and shutil.which("networksetup") is not None

    def _services(self) -> list[str]:
        result = _run(["networksetup", "-listallnetworkservices"])
        services = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("An asterisk") or line.startswith("*"):
                continue
            services.append(line)
        return services

    def enable(self, host: str = "127.0.0.1", port: int | None = None) -> dict[str, Any]:
        port = port or self.settings.mixed_port
        original: dict[str, Any] = {}
        for service in self._services():
            states: dict[str, Any] = {}
            getters = {
                "web": "-getwebproxy",
                "secure": "-getsecurewebproxy",
                "socks": "-getsocksfirewallproxy",
            }
            for kind, get_flag in getters.items():
                result = _run(["networksetup", get_flag, service])
                enabled = "Enabled: Yes" in result.stdout
                server = ""
                port_value = 0
                for line in result.stdout.splitlines():
                    if line.startswith("Server:"):
                        server = line.split(":", 1)[1].strip()
                    if line.startswith("Port:"):
                        try:
                            port_value = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            port_value = 0
                states[kind] = {"enabled": enabled, "server": server, "port": port_value}
            original[service] = states
            _run(["networksetup", "-setwebproxy", service, host, str(port)])
            _run(["networksetup", "-setsecurewebproxy", service, host, str(port)])
            _run(["networksetup", "-setsocksfirewallproxy", service, host, str(port)])
        state = _read_state(self.state_path)
        state[STATE_KEY] = {
            "platform": self.platform,
            "enabled": True,
            "host": host,
            "port": port,
            "original": original,
            "clean_shutdown": False,
        }
        _write_state(self.state_path, state)
        return self.status()

    def disable(self) -> dict[str, Any]:
        state = _read_state(self.state_path)
        entry = state.get(STATE_KEY, {})
        for service, kinds in (entry.get("original") or {}).items():
            for kind, value in kinds.items():
                flag = {
                    "web": "-setwebproxy",
                    "secure": "-setsecurewebproxy",
                    "socks": "-setsocksfirewallproxy",
                }[kind]
                off_flag = {
                    "web": "-setwebproxystate",
                    "secure": "-setsecurewebproxystate",
                    "socks": "-setsocksfirewallproxystate",
                }[kind]
                if value.get("enabled") and value.get("server"):
                    _run(["networksetup", flag, service, value["server"], str(value["port"])])
                else:
                    _run(["networksetup", off_flag, service, "off"])
        entry.update({"enabled": False, "clean_shutdown": True})
        state[STATE_KEY] = entry
        _write_state(self.state_path, state)
        return self.status()


class WindowsProxy(BaseProxy):
    platform = "windows"

    @property
    def supported(self) -> bool:
        return sys.platform == "win32"

    def enable(self, host: str = "127.0.0.1", port: int | None = None) -> dict[str, Any]:
        port = port or self.settings.mixed_port
        import winreg  # pragma: no cover - Windows only

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ | winreg.KEY_WRITE
        ) as key:
            original = {}
            for name in ("ProxyEnable", "ProxyServer", "ProxyOverride", "AutoConfigURL"):
                try:
                    original[name] = winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    original[name] = None
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")
            # A PAC URL takes precedence over the manual proxy on Windows.
            # Remove it while the proxy is active and restore it on disable.
            try:
                winreg.DeleteValue(key, "AutoConfigURL")
            except FileNotFoundError:
                pass
            winreg.SetValueEx(
                key,
                "ProxyOverride",
                0,
                winreg.REG_SZ,
                "localhost;127.*;10.*;172.16.*;172.17.*;172.18.*;172.19.*;172.20.*;172.21.*;172.22.*;172.23.*;172.24.*;172.25.*;172.26.*;172.27.*;172.28.*;172.29.*;172.30.*;172.31.*;192.168.*;<local>",
            )
        _notify_wininet()
        state = _read_state(self.state_path)
        state[STATE_KEY] = {
            "platform": self.platform,
            "enabled": True,
            "host": host,
            "port": port,
            "original": original,
            "clean_shutdown": False,
        }
        _write_state(self.state_path, state)
        return self.status()

    def disable(self) -> dict[str, Any]:
        import winreg  # pragma: no cover - Windows only

        state = _read_state(self.state_path)
        entry = state.get(STATE_KEY, {})
        original = entry.get("original") or {}
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ | winreg.KEY_WRITE
        ) as key:
            if original.get("ProxyEnable") is not None:
                winreg.SetValueEx(
                    key, "ProxyEnable", 0, winreg.REG_DWORD, int(original["ProxyEnable"])
                )
            else:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            if original.get("ProxyServer") is not None:
                winreg.SetValueEx(
                    key, "ProxyServer", 0, winreg.REG_SZ, str(original["ProxyServer"])
                )
            else:
                try:
                    winreg.DeleteValue(key, "ProxyServer")
                except FileNotFoundError:
                    pass
            if original.get("ProxyOverride") is not None:
                winreg.SetValueEx(
                    key, "ProxyOverride", 0, winreg.REG_SZ, str(original["ProxyOverride"])
                )
            else:
                try:
                    winreg.DeleteValue(key, "ProxyOverride")
                except FileNotFoundError:
                    pass
            if original.get("AutoConfigURL") is not None:
                winreg.SetValueEx(
                    key, "AutoConfigURL", 0, winreg.REG_SZ, str(original["AutoConfigURL"])
                )
            else:
                try:
                    winreg.DeleteValue(key, "AutoConfigURL")
                except FileNotFoundError:
                    pass
        _notify_wininet()
        entry.update({"enabled": False, "clean_shutdown": True})
        state[STATE_KEY] = entry
        _write_state(self.state_path, state)
        return self.status()


def _notify_wininet() -> None:  # pragma: no cover - Windows only
    import ctypes

    internet_option_settings_changed = 39
    internet_option_refresh = 37
    ctypes.windll.Wininet.InternetSetOptionW(0, internet_option_settings_changed, 0, 0)
    ctypes.windll.Wininet.InternetSetOptionW(0, internet_option_refresh, 0, 0)


def system_proxy(settings: Settings) -> BaseProxy:
    if sys.platform == "win32":
        return WindowsProxy(settings)
    if sys.platform == "darwin":
        return MacProxy(settings)
    gnome = GnomeProxy(settings)
    if gnome.supported:
        return gnome
    kde = KdeProxy(settings)
    if kde.supported:
        return kde
    return BaseProxy(settings)


def env_hint(port: int) -> str:
    return (
        f"export http_proxy=http://127.0.0.1:{port}\n"
        f"export https_proxy=http://127.0.0.1:{port}\n"
        f"export all_proxy=socks5://127.0.0.1:{port}\n"
    )
