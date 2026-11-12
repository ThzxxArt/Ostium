"""Runtime configuration and filesystem layout.

The same wheel runs as either a server or a client.  Configuration is read from
``$OSTIUM_CONFIG_FILE`` (default ``/etc/ostium/config.toml`` on installed server
deployments, otherwise ``<data_dir>/config.toml``), then overridden by
``OSTIUM_*`` environment variables.  This keeps development, tests, Docker and
systemd deployments on one deterministic code path.
"""

from __future__ import annotations

import os
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any

from platformdirs import user_config_path, user_data_path, user_state_path
from pydantic import BaseModel, Field, field_validator


class Role(StrEnum):
    SERVER = "server"
    CLIENT = "client"


class Mode(StrEnum):
    MIXED = "mixed"
    SYSTEM_PROXY = "system_proxy"
    TUN = "tun"


def _default_data_dir(role: Role) -> Path:
    override = os.environ.get("OSTIUM_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if role is Role.SERVER and os.name == "posix" and os.geteuid() == 0:
        return Path("/var/lib/ostium")
    return Path(user_data_path("ostium", appauthor=False))


def _default_config_dir(role: Role) -> Path:
    override = os.environ.get("OSTIUM_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    if role is Role.SERVER and os.name == "posix" and os.geteuid() == 0:
        return Path("/etc/ostium")
    return Path(user_config_path("ostium", appauthor=False))


class Paths(BaseModel):
    """All mutable filesystem locations, derived once at startup."""

    data_dir: Path
    config_dir: Path
    state_dir: Path
    runtime_dir: Path
    logs_dir: Path
    certs_dir: Path
    backups_dir: Path
    rulesets_dir: Path
    web_dist: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ostium.db"

    @property
    def master_key_path(self) -> Path:
        return self.data_dir / "master.key"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def core_token_path(self) -> Path:
        return self.runtime_dir / "core.token"

    @property
    def core_state_path(self) -> Path:
        return self.runtime_dir / "core-state.json"

    @property
    def last_good_path(self) -> Path:
        return self.runtime_dir / "last-good.json"

    @property
    def clash_secret_path(self) -> Path:
        return self.runtime_dir / "clash.secret"

    @property
    def engine_binary(self) -> Path:
        return self.data_dir / "core" / ("sing-box.exe" if os.name == "nt" else "sing-box")

    @property
    def state_file(self) -> Path:
        return self.state_dir / "ui-state.json"

    def ensure(self) -> None:
        for path in (
            self.data_dir,
            self.config_dir,
            self.state_dir,
            self.runtime_dir,
            self.logs_dir,
            self.certs_dir,
            self.backups_dir,
            self.rulesets_dir,
            self.data_dir / "core",
        ):
            path.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            for path in (self.data_dir, self.runtime_dir):
                try:
                    path.chmod(0o700)
                except OSError:
                    pass


class Settings(BaseModel):
    """Effective process configuration."""

    role: Role = Role.SERVER
    host: str = "127.0.0.1"
    port: int = 8443
    public_ui: bool = False
    data_dir: Path
    config_dir: Path
    state_dir: Path
    log_level: str = "info"
    core_url: str = "http://127.0.0.1:8788"
    core_token_file: Path
    engine_path: Path | None = None
    engine_version: str = "1.14.4-ostium.1"
    acme_email: str | None = None
    acme_directory: str = "https://acme-v02.api.letsencrypt.org/directory"
    acme_staging: bool = False
    trusted_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1", "::1"])
    secure_cookies: bool = False
    telemetry: bool = False
    mode: Mode = Mode.MIXED
    mixed_port: int = 7890
    allow_lan: bool = False
    tun_enabled: bool = False
    tun_interface: str = "ostium0"
    proxy_ports: list[int] = Field(default_factory=lambda: [443, 8388])
    auto_connect: bool = False
    auto_reconnect: bool = True
    dev: bool = False

    @field_validator("log_level")
    @classmethod
    def _normalise_level(cls, value: str) -> str:
        return value.lower()

    @property
    def paths(self) -> Paths:
        return Paths(
            data_dir=self.data_dir,
            config_dir=self.config_dir,
            state_dir=self.state_dir,
            runtime_dir=self.data_dir / "runtime",
            logs_dir=self.data_dir / "logs",
            certs_dir=self.data_dir / "certs",
            backups_dir=self.data_dir / "backups",
            rulesets_dir=self.data_dir / "rulesets",
            web_dist=_locate_web_dist(),
        )

    def save(self, path: Path | None = None) -> Path:
        """Persist the non-secret parts of the configuration as TOML."""

        import tomli_w

        target = (
            path
            or Paths(
                data_dir=self.data_dir,
                config_dir=self.config_dir,
                state_dir=self.state_dir,
                runtime_dir=self.data_dir / "runtime",
                logs_dir=self.data_dir / "logs",
                certs_dir=self.data_dir / "certs",
                backups_dir=self.data_dir / "backups",
                rulesets_dir=self.data_dir / "rulesets",
            ).config_file
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "role": self.role.value,
            "host": self.host,
            "port": self.port,
            "public_ui": self.public_ui,
            "data_dir": str(self.data_dir),
            "config_dir": str(self.config_dir),
            "log_level": self.log_level,
            "core_url": self.core_url,
            "engine_version": self.engine_version,
            "acme_email": self.acme_email,
            "acme_directory": self.acme_directory,
            "acme_staging": self.acme_staging,
            "trusted_hosts": self.trusted_hosts,
            "secure_cookies": self.secure_cookies,
            "mode": self.mode.value,
            "mixed_port": self.mixed_port,
            "allow_lan": self.allow_lan,
            "tun_enabled": self.tun_enabled,
            "tun_interface": self.tun_interface,
            "proxy_ports": self.proxy_ports,
            "auto_connect": self.auto_connect,
            "auto_reconnect": self.auto_reconnect,
            "dev": self.dev,
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        tomli_w.dump(payload, target.open("wb"))
        if os.name == "posix":
            target.chmod(0o600)
        return target

    @classmethod
    def load(cls, config_file: Path | None = None) -> Settings:
        env_role = Role(os.environ.get("OSTIUM_ROLE", Role.SERVER.value))
        initial_config = _default_config_dir(env_role)
        candidate = config_file or Path(
            os.environ.get("OSTIUM_CONFIG_FILE", initial_config / "config.toml")
        )
        raw: dict[str, Any] = {}
        if candidate.is_file():
            with candidate.open("rb") as handle:
                raw = tomllib.load(handle)
        role = Role(os.environ.get("OSTIUM_ROLE", raw.get("role", Role.SERVER.value)))
        data_dir = Path(
            os.environ.get("OSTIUM_DATA_DIR", raw.get("data_dir", _default_data_dir(role)))
        ).expanduser()
        config_dir = Path(
            os.environ.get("OSTIUM_CONFIG_DIR", raw.get("config_dir", _default_config_dir(role)))
        ).expanduser()
        state_dir = Path(
            os.environ.get(
                "OSTIUM_STATE_DIR",
                raw.get("state_dir", user_state_path("ostium", appauthor=False)),
            )
        ).expanduser()
        default_host = "0.0.0.0" if role is Role.SERVER else "127.0.0.1"
        default_port = 8443 if role is Role.SERVER else 8787
        default_token = data_dir / "runtime" / "core.token"
        if role is Role.CLIENT and Path("/var/lib/ostium-core/core.token").is_file():
            default_token = Path("/var/lib/ostium-core/core.token")
        base = {
            "role": role,
            "host": raw.get("host", default_host),
            "port": raw.get("port", default_port),
            "public_ui": raw.get("public_ui", False),
            "data_dir": data_dir,
            "config_dir": config_dir,
            "state_dir": state_dir,
            "log_level": raw.get("log_level", "info"),
            "core_url": raw.get("core_url", "http://127.0.0.1:8788"),
            "core_token_file": Path(
                os.environ.get(
                    "OSTIUM_CORE_TOKEN_FILE",
                    raw.get("core_token_file", default_token),
                )
            ),
            "engine_path": raw.get("engine_path"),
            "engine_version": raw.get("engine_version", "1.14.4-ostium.1"),
            "acme_email": raw.get("acme_email"),
            "acme_directory": raw.get(
                "acme_directory", "https://acme-v02.api.letsencrypt.org/directory"
            ),
            "acme_staging": raw.get("acme_staging", False),
            "trusted_hosts": raw.get("trusted_hosts", ["localhost", "127.0.0.1", "::1"]),
            "secure_cookies": raw.get("secure_cookies", False),
            "mode": raw.get("mode", Mode.MIXED.value),
            "mixed_port": raw.get("mixed_port", 7890),
            "allow_lan": raw.get("allow_lan", False),
            "tun_enabled": raw.get("tun_enabled", False),
            "tun_interface": raw.get("tun_interface", "ostium0"),
            "proxy_ports": raw.get("proxy_ports", [443, 8388]),
            "auto_connect": raw.get("auto_connect", False),
            "auto_reconnect": raw.get("auto_reconnect", True),
            "dev": raw.get("dev", False),
        }
        env_map: dict[str, tuple[str, Any]] = {
            "OSTIUM_HOST": ("host", str),
            "OSTIUM_PORT": ("port", int),
            "OSTIUM_PUBLIC_UI": ("public_ui", _as_bool),
            "OSTIUM_LOG_LEVEL": ("log_level", str),
            "OSTIUM_CORE_URL": ("core_url", str),
            "OSTIUM_ENGINE_PATH": ("engine_path", str),
            "OSTIUM_ACME_EMAIL": ("acme_email", str),
            "OSTIUM_ACME_STAGING": ("acme_staging", _as_bool),
            "OSTIUM_SECURE_COOKIES": ("secure_cookies", _as_bool),
            "OSTIUM_MODE": ("mode", Mode),
            "OSTIUM_MIXED_PORT": ("mixed_port", int),
            "OSTIUM_ALLOW_LAN": ("allow_lan", _as_bool),
            "OSTIUM_TUN_ENABLED": ("tun_enabled", _as_bool),
            "OSTIUM_TUN_INTERFACE": ("tun_interface", str),
            "OSTIUM_PROXY_PORTS": ("proxy_ports", _as_ports),
            "OSTIUM_DEV": ("dev", _as_bool),
        }
        for env_name, (field, caster) in env_map.items():
            if env_name in os.environ:
                base[field] = caster(os.environ[env_name])
        if base["engine_path"] in (None, ""):
            base["engine_path"] = str(
                data_dir / "core" / ("sing-box.exe" if os.name == "nt" else "sing-box")
            )
        settings = cls.model_validate(base)
        settings.paths.ensure()
        return settings


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_ports(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _locate_web_dist() -> Path | None:
    here = Path(__file__).resolve().parent
    candidates = [
        here / "web" / "dist",
        here.parent.parent / "web" / "dist",
    ]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


def cached_settings() -> Settings:
    """Process-wide settings accessor used by CLI and web entrypoints."""

    global _SETTINGS
    try:
        return _SETTINGS
    except NameError:
        _SETTINGS = Settings.load()
        return _SETTINGS


def set_settings(settings: Settings) -> None:
    global _SETTINGS
    _SETTINGS = settings


_SETTINGS: Settings
