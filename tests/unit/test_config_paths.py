from __future__ import annotations

import os
from pathlib import Path

import pytest

from ostium import config as config_module
from ostium.config import (
    Mode,
    Paths,
    Role,
    Settings,
    _as_bool,
    _as_ports,
    _default_config_dir,
    _default_data_dir,
    _locate_web_dist,
    cached_settings,
    set_settings,
)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    data = tmp_path / "data"
    value = Settings(
        data_dir=data,
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=data / "runtime" / "core.token",
        **overrides,
    )
    return value


def test_paths_properties_and_ensure(tmp_path: Path) -> None:
    value = _settings(tmp_path)
    paths = value.paths
    assert paths.db_path == value.data_dir / "ostium.db"
    assert paths.master_key_path == value.data_dir / "master.key"
    assert paths.config_file == value.config_dir / "config.toml"
    assert paths.core_token_path == value.data_dir / "runtime" / "core.token"
    assert paths.core_state_path == value.data_dir / "runtime" / "core-state.json"
    assert paths.last_good_path == value.data_dir / "runtime" / "last-good.json"
    assert paths.clash_secret_path == value.data_dir / "runtime" / "clash.secret"
    assert paths.engine_binary == value.data_dir / "core" / "sing-box"
    assert paths.state_file == value.state_dir / "ui-state.json"

    paths.ensure()
    for directory in (
        value.data_dir,
        value.config_dir,
        value.state_dir,
        paths.runtime_dir,
        paths.logs_dir,
        paths.certs_dir,
        paths.backups_dir,
        paths.rulesets_dir,
        value.data_dir / "core",
    ):
        assert directory.is_dir()
    if os.name == "posix":
        assert (value.data_dir.stat().st_mode & 0o777) == 0o700
        assert (paths.runtime_dir.stat().st_mode & 0o777) == 0o700


def test_shared_client_directories_are_group_traversable(tmp_path: Path) -> None:
    value = _settings(tmp_path, role=Role.CLIENT, shared_data=True)
    paths = value.paths
    paths.ensure()
    if os.name == "posix":
        assert (value.data_dir.stat().st_mode & 0o777) == 0o750
        assert (paths.runtime_dir.stat().st_mode & 0o777) == 0o750


def test_engine_binary_windows_suffix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    value = _settings(tmp_path)
    monkeypatch.setattr(config_module, "os", types.SimpleNamespace(name="nt"))
    assert value.paths.engine_binary.name == "sing-box.exe"


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    value = _settings(
        tmp_path,
        role=Role.CLIENT,
        host="127.0.0.1",
        port=9999,
        public_ui=False,
        log_level="DEBUG",
        acme_email="a@example.com",
        acme_staging=True,
        trusted_hosts=["example.com"],
        secure_cookies=True,
        mode=Mode.TUN,
        mixed_port=7891,
        tun_enabled=True,
        tun_interface="ostium9",
        proxy_ports=[1, 2],
        auto_connect=True,
        auto_reconnect=False,
        dev=True,
    )
    value.paths.ensure()
    target = value.save()
    assert target.is_file()
    if os.name == "posix":
        assert (target.stat().st_mode & 0o777) == 0o600

    loaded = Settings.load(target)
    assert loaded.role is Role.CLIENT
    assert loaded.host == "127.0.0.1"
    assert loaded.log_level == "debug"
    assert loaded.mode is Mode.TUN
    assert loaded.tun_enabled is True
    assert loaded.proxy_ports == [1, 2]
    assert loaded.auto_reconnect is False


def test_save_to_explicit_path_and_none_fields(tmp_path: Path) -> None:
    value = _settings(tmp_path, acme_email=None)
    explicit = tmp_path / "custom" / "config.toml"
    saved = value.save(explicit)
    assert saved == explicit
    assert "acme_email" not in explicit.read_text()


def test_loaded_client_config_saves_back_to_the_same_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = tmp_path / "etc"
    client_config = config_dir / "client.toml"
    client_config.parent.mkdir(parents=True)
    client_config.write_text('role = "client"\nport = 8787\n', encoding="utf-8")
    monkeypatch.setenv("OSTIUM_CONFIG_FILE", str(client_config))
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("OSTIUM_STATE_DIR", str(tmp_path / "state"))

    loaded = Settings.load(client_config)
    assert loaded.config_file == client_config
    loaded.mixed_port = 7891
    saved = loaded.save()

    assert saved == client_config
    assert "mixed_port = 7891" in client_config.read_text()
    # The generic config.toml must not be created behind the client's back.
    assert not (config_dir / "config.toml").exists()


def test_load_environment_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config" / "config.toml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        "\n".join(
            [
                'role = "server"',
                f'data_dir = "{tmp_path / "raw-data"}"',
                f'config_dir = "{tmp_path / "raw-config"}"',
                f'state_dir = "{tmp_path / "raw-state"}"',
                'host = "10.0.0.1"',
                "port = 7000",
                'log_level = "WARNING"',
                'mode = "mixed"',
                "proxy_ports = [443]",
            ]
        )
    )
    env = {
        "OSTIUM_CONFIG_FILE": str(config_file),
        "OSTIUM_ROLE": "client",
        "OSTIUM_DATA_DIR": str(tmp_path / "data"),
        "OSTIUM_CONFIG_DIR": str(tmp_path / "config"),
        "OSTIUM_STATE_DIR": str(tmp_path / "state"),
        "OSTIUM_HOST": "127.0.0.1",
        "OSTIUM_PORT": "8888",
        "OSTIUM_PUBLIC_UI": "yes",
        "OSTIUM_LOG_LEVEL": "TRACE",
        "OSTIUM_CORE_URL": "http://127.0.0.1:9999",
        "OSTIUM_ENGINE_PATH": str(tmp_path / "bin" / "sing-box"),
        "OSTIUM_ACME_EMAIL": "b@example.com",
        "OSTIUM_ACME_STAGING": "on",
        "OSTIUM_SECURE_COOKIES": "true",
        "OSTIUM_MODE": "system_proxy",
        "OSTIUM_MIXED_PORT": "7899",
        "OSTIUM_TUN_ENABLED": "1",
        "OSTIUM_TUN_INTERFACE": "tun9",
        "OSTIUM_PROXY_PORTS": "443, 8443,8388",
        "OSTIUM_DEV": "yes",
    }
    for key, item in env.items():
        monkeypatch.setenv(key, item)
    monkeypatch.setattr(
        Path, "is_file", lambda self: self == Path("/var/lib/ostium-core/core.token")
    )

    loaded = Settings.load()
    assert loaded.role is Role.CLIENT
    assert loaded.host == "127.0.0.1"
    assert loaded.port == 8888
    assert loaded.public_ui is True
    assert loaded.log_level == "trace"
    assert loaded.core_url == "http://127.0.0.1:9999"
    assert loaded.engine_path == tmp_path / "bin" / "sing-box"
    assert loaded.acme_email == "b@example.com"
    assert loaded.acme_staging is True
    assert loaded.secure_cookies is True
    assert loaded.mode is Mode.SYSTEM_PROXY
    assert loaded.mixed_port == 7899
    assert loaded.tun_enabled is True
    assert loaded.tun_interface == "tun9"
    assert loaded.proxy_ports == [443, 8443, 8388]
    assert loaded.dev is True
    assert loaded.core_token_file == Path("/var/lib/ostium-core/core.token")


def test_load_defaults_for_missing_file_and_empty_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = tmp_path / "missing.toml"
    monkeypatch.setenv("OSTIUM_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OSTIUM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OSTIUM_ENGINE_PATH", "")
    monkeypatch.delenv("OSTIUM_ROLE", raising=False)
    monkeypatch.setattr(Path, "is_file", lambda self: False)

    loaded = Settings.load()
    assert loaded.role is Role.SERVER
    assert loaded.host == "0.0.0.0"
    assert loaded.port == 8443
    assert loaded.engine_path == tmp_path / "data" / "core" / (
        "sing-box.exe" if os.name == "nt" else "sing-box"
    )


def test_load_client_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OSTIUM_CONFIG_FILE", str(tmp_path / "missing.toml"))
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OSTIUM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OSTIUM_ROLE", "client")
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    loaded = Settings.load()
    assert loaded.host == "127.0.0.1"
    assert loaded.port == 8787
    assert loaded.core_token_file == tmp_path / "data" / "runtime" / "core.token"


def test_default_directories_for_root_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OSTIUM_DATA_DIR", raising=False)
    monkeypatch.delenv("OSTIUM_CONFIG_DIR", raising=False)
    monkeypatch.setattr(config_module.os, "geteuid", lambda: 0)
    assert _default_data_dir(Role.SERVER) == Path("/var/lib/ostium")
    assert _default_config_dir(Role.SERVER) == Path("/etc/ostium")
    assert _default_data_dir(Role.CLIENT) != Path("/var/lib/ostium")


def test_default_directory_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(tmp_path / "override-data"))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(tmp_path / "override-config"))
    assert _default_data_dir(Role.SERVER) == tmp_path / "override-data"
    assert _default_config_dir(Role.SERVER) == tmp_path / "override-config"


def test_locate_web_dist_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = tmp_path / "pkg" / "config.py"
    fake_module.parent.mkdir(parents=True)
    monkeypatch.setattr(config_module, "__file__", str(fake_module))
    assert _locate_web_dist() is None

    dist = fake_module.parent / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("ok")
    assert _locate_web_dist() == dist


def test_locate_web_dist_parent_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    here = tmp_path / "a" / "b" / "ostium"
    here.mkdir(parents=True)
    monkeypatch.setattr(config_module, "__file__", str(here / "config.py"))
    dist = tmp_path / "a" / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("ok")
    assert _locate_web_dist() == dist


def test_settings_validators_and_cached_accessor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _as_bool(" YES ") is True
    assert _as_bool("0") is False
    assert _as_ports("1, 2,,3") == [1, 2, 3]
    value = _settings(tmp_path, log_level="WARNING")
    assert value.log_level == "warning"

    monkeypatch.delenv("OSTIUM_DATA_DIR", raising=False)
    set_settings(value)
    assert cached_settings() is value

    # Simulate a fresh process where the cache has never been populated.
    monkeypatch.delattr(config_module, "_SETTINGS")
    monkeypatch.setenv("OSTIUM_DATA_DIR", str(tmp_path / "fresh"))
    monkeypatch.setenv("OSTIUM_CONFIG_DIR", str(tmp_path / "fresh-config"))
    monkeypatch.setenv("OSTIUM_STATE_DIR", str(tmp_path / "fresh-state"))
    monkeypatch.setenv("OSTIUM_CONFIG_FILE", str(tmp_path / "fresh.toml"))
    fresh = cached_settings()
    assert fresh.data_dir == tmp_path / "fresh"
    assert cached_settings() is fresh


def test_paths_accepts_optional_web_dist(tmp_path: Path) -> None:
    paths = Paths(
        data_dir=tmp_path / "d",
        config_dir=tmp_path / "c",
        state_dir=tmp_path / "s",
        runtime_dir=tmp_path / "d" / "runtime",
        logs_dir=tmp_path / "d" / "logs",
        certs_dir=tmp_path / "d" / "certs",
        backups_dir=tmp_path / "d" / "backups",
        rulesets_dir=tmp_path / "d" / "rulesets",
    )
    assert paths.web_dist is None
