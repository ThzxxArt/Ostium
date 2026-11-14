"""Ostium command line interface."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import platform
import shutil
import sys
import tarfile
import webbrowser
from pathlib import Path
from typing import Any, NoReturn, cast

import httpx
import typer
from rich.console import Console
from rich.table import Table

from ostium import __version__
from ostium.config import Mode, Role, Settings, is_loopback_host
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.crypto import SecretStore

app = typer.Typer(
    name="ostium",
    help="Ostium — dual-role personal VPN and proxy console.",
    no_args_is_help=True,
    add_completion=True,
)
user_app = typer.Typer(help="Manage proxy users (server).", no_args_is_help=True)
profile_app = typer.Typer(help="Manage client profiles.", no_args_is_help=True)
core_app = typer.Typer(help="Manage the sing-box core binary.", no_args_is_help=True)
backup_app = typer.Typer(help="Create and restore backups.", no_args_is_help=True)
cert_app = typer.Typer(help="Manage TLS certificates.", no_args_is_help=True)
service_app = typer.Typer(help="Install or remove system services.", no_args_is_help=True)
app.add_typer(user_app, name="user")
app.add_typer(profile_app, name="profile")
app.add_typer(core_app, name="core")
app.add_typer(backup_app, name="backup")
app.add_typer(cert_app, name="cert")
app.add_typer(service_app, name="service")

console = Console()
err_console = Console(stderr=True)

_ALLOW_DEGRADED = os.environ.get("OSTIUM_ALLOW_DEGRADED", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


@app.callback()
def _main(
    allow_degraded: bool = typer.Option(
        False,
        "--allow-degraded",
        help="Continue with exit code 0 when a configuration cannot be applied",
    ),
) -> None:
    """Ostium command line interface."""

    global _ALLOW_DEGRADED
    if allow_degraded:
        _ALLOW_DEGRADED = True


def _load_settings() -> Settings:
    return Settings.load()


def _json(value: Any) -> None:
    console.print_json(json.dumps(value, ensure_ascii=False, default=str))


async def _audit(session: Any, action: str, target: str | None = None, **detail: Any) -> None:
    """Record CLI-initiated database changes in the audit trail."""

    from ostium.services.audit import audit

    await audit(session, actor="cli", action=action, target=target, detail=detail or None)


def _audit_sync(settings: Settings, action: str, target: str | None = None, **detail: Any) -> None:
    async def _write() -> None:
        engine, factory, _store = await _database(settings)
        try:
            async with factory() as session:
                await _audit(session, action, target, **detail)
                await session.commit()
        finally:
            await engine.dispose()

    try:
        _run(_write())
    except Exception:
        # Auditing must never turn a successful backup/restore into a failure;
        # the operation itself is still reported by its own output.
        pass


async def _database(settings: Settings) -> tuple[Any, Any, SecretStore]:
    engine = create_engine(settings.paths.db_path)
    await create_schema(engine)
    factory = create_session_factory(engine)
    store = SecretStore.from_data_dir(settings.data_dir)
    return engine, factory, store


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _fail(message: str, code: int = 1) -> NoReturn:
    err_console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code)


def _base_url(settings: Settings) -> str:
    scheme = "https" if settings.public_ui else "http"
    return f"{scheme}://127.0.0.1:{settings.port}"


def _engine_binary(settings: Settings) -> Path:
    """Return the configured core binary, not only the data-dir default."""

    return Path(settings.engine_path or settings.paths.engine_binary)


def _api(settings: Settings, method: str, path: str, **kwargs: Any) -> Any:
    token_path = settings.paths.runtime_dir / "cli.token"
    if not token_path.is_file():
        _fail("CLI token not found; start the Ostium service first", 4)
    headers = {"Authorization": f"Bearer {token_path.read_text().strip()}"}
    try:
        response = httpx.request(
            method,
            f"{_base_url(settings)}{path}",
            headers=headers,
            timeout=30,
            trust_env=False,
            # The local listener may present a valid ACME or a self-signed
            # certificate.  This is a loopback-only CLI call authenticated by
            # a 0600 token; pinning the local certificate would make `ostium
            # status` unusable on self-signed Public UI installs.
            verify=False,  # noqa: S501 - loopback-only, token-authenticated CLI call
            **kwargs,
        )
    except httpx.HTTPError as exc:
        _fail(f"Ostium service is not reachable: {exc}", 4)
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        _fail(f"{response.status_code}: {detail}", 1)
    return response.json() if response.content else {}


@app.command()
def version() -> None:
    """Print the Ostium version and build identifiers."""

    console.print(f"Ostium {__version__}")
    console.print(f"Python {sys.version.split()[0]} on {platform.platform()}")


@app.command()
def init(
    role: str = typer.Option("server", "--role", help="server or client"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    config_dir: Path | None = typer.Option(None, "--config-dir"),
    dev: bool = typer.Option(False, "--dev", help="Local development defaults"),
    username: str = typer.Option("admin", "--username"),
    password: str | None = typer.Option(None, "--password"),
    domain: str | None = typer.Option(None, "--domain"),
    host: str | None = typer.Option(None, "--host", help="UI listen address"),
    port: int | None = typer.Option(None, "--port", help="UI listen port"),
    public_ui: bool = typer.Option(False, "--public-ui/--no-public-ui"),
    allow_insecure_bind: bool = typer.Option(
        False,
        "--allow-insecure-bind",
        help="Explicitly permit a non-loopback plaintext admin UI",
    ),
    no_input: bool = typer.Option(False, "--no-input"),
    force: bool = typer.Option(
        False, "--force", help="Reinitialise configuration files (never deletes data)"
    ),
) -> None:
    """Initialise an Ostium server or client data directory."""

    try:
        role_value = Role(role)
    except ValueError:
        _fail("--role must be server or client", 2)
    try:
        settings = Settings.load()
    except Exception:
        settings = Settings(
            role=role_value,
            data_dir=Path(),
            config_dir=Path(),
            state_dir=Path(),
            core_token_file=Path(),
        )
    if data_dir:
        settings.data_dir = data_dir
        if "OSTIUM_STATE_DIR" not in os.environ:
            settings.state_dir = data_dir / "state"
    if config_dir:
        settings.config_dir = config_dir
        settings.config_path = config_dir / "config.toml"
    settings.role = role_value
    settings.dev = dev
    configured_host = host or os.environ.get("OSTIUM_HOST") or "127.0.0.1"
    configured_allow = allow_insecure_bind or (
        os.environ.get("OSTIUM_ALLOW_INSECURE_BIND", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    settings.host = configured_host
    settings.port = port or (8443 if role_value is Role.SERVER else 8787)
    settings.public_ui = public_ui and role_value is Role.SERVER
    settings.allow_insecure_bind = configured_allow and role_value is Role.SERVER
    if (
        role_value is Role.SERVER
        and not settings.public_ui
        and not settings.allow_insecure_bind
        and not is_loopback_host(settings.host)
    ):
        _fail(
            f"--host {settings.host} would expose the admin UI over plaintext HTTP; "
            "use 127.0.0.1 or pass --allow-insecure-bind explicitly",
            2,
        )
    if settings.public_ui and not settings.allow_insecure_bind:
        # Public UI terminates TLS itself, so no insecure-bind opt-in is needed.
        settings.allow_insecure_bind = False
    if role_value is Role.SERVER or settings.dev:
        settings.core_token_file = settings.data_dir / "runtime" / "core.token"
    if role_value is Role.SERVER and domain:
        settings.trusted_hosts = sorted({*settings.trusted_hosts, domain.strip().lower()})
    settings.paths.ensure()
    settings.save()

    async def _init() -> tuple[str, bool]:
        engine, factory, store = await _database(settings)
        from ostium.services.auth import create_admin, get_admin
        from ostium.services.settings import is_initialized, set_setting
        from ostium.services.users import ensure_inbounds
        from ostium.util.ids import new_password

        generated = False
        try:
            async with factory() as session:
                if await is_initialized(session) and not force:
                    admin = await get_admin(session)
                    return (admin.username if admin else "admin"), False
                admin = await get_admin(session)
                actual_password = password
                if admin is None:
                    if not actual_password:
                        actual_password = new_password(18)
                        generated = True
                    admin = await create_admin(
                        session,
                        username=username,
                        password=actual_password,
                        must_change_password=False,
                    )
                elif actual_password:
                    from ostium.services.auth import set_password

                    await set_password(session, admin, actual_password)
                if role_value is Role.SERVER:
                    await ensure_inbounds(session, store)
                await set_setting(session, "initialized", True)
                from ostium.services.settings import get_setting

                previous_server = await get_setting(session, "server", {})
                if not isinstance(previous_server, dict):
                    previous_server = {}
                effective_domain = domain or previous_server.get("domain")
                server_info = {
                    "domain": effective_domain,
                    "public_host": effective_domain,
                    "public_ui": settings.public_ui
                    if domain
                    else bool(previous_server.get("public_ui", settings.public_ui)),
                }
                await set_setting(session, "server", server_info)
                if effective_domain:
                    await set_setting(session, "public_base_url", f"https://{effective_domain}")
                await session.commit()
                if generated:
                    console.print(
                        "[bold yellow]Generated administrator password (save it now):[/bold yellow]"
                    )
                    console.print(f"  {actual_password}")
                return admin.username, generated
        finally:
            await engine.dispose()

    username_value, generated = _run(_init())
    console.print(f"[green]Ostium {role_value.value} initialised[/green] at {settings.data_dir}")
    console.print(f"Admin user: [bold]{username_value}[/bold]")
    if generated:
        console.print("[yellow]The password above is shown only once.[/yellow]")
    console.print("Next: `ostium serve` (control plane) and `ostium core-run` (core service).")


@app.command()
def serve(
    host: str | None = typer.Option(None, "--host"),
    port: int | None = typer.Option(None, "--port"),
    allow_insecure_bind: bool = typer.Option(
        False,
        "--allow-insecure-bind",
        help="Explicitly permit a non-loopback plaintext admin UI",
    ),
    reload: bool = typer.Option(False, "--reload", help="Development auto-reload"),
) -> None:
    """Run the Ostium control plane (Web UI + API)."""

    import uvicorn

    from ostium.api.app import build_app
    from ostium.services.backup import apply_pending_restore

    settings = _load_settings()
    if host:
        settings.host = host
    if port:
        settings.port = port
    if allow_insecure_bind:
        settings.allow_insecure_bind = True
    if settings.host_migrated:
        err_console.print(
            "[yellow]Legacy host=0.0.0.0 was migrated to 127.0.0.1 for safety. "
            "Use an SSH tunnel, Public UI with TLS, or allow_insecure_bind = true "
            "to expose the admin UI deliberately.[/yellow]"
        )
        with contextlib.suppress(OSError):
            settings.save()
    try:
        settings.validate_bind()
    except Exception as exc:
        err_console.print(f"[red]refusing to start:[/red] {exc}")
        raise typer.Exit(code=6) from exc
    if settings.allow_insecure_bind and not is_loopback_host(settings.host):
        err_console.print(
            "[yellow]warning: admin UI is listening on a non-loopback plaintext address "
            "because allow_insecure_bind is enabled; restrict the port with a firewall.[/yellow]"
        )
    try:
        result = apply_pending_restore(settings)
        if result:
            console.print("[green]Staged backup restored before startup.[/green]")
    except Exception as exc:
        err_console.print(
            f"[yellow]warning: staged backup restore failed and was kept for retry: {exc}[/yellow]"
        )
    ssl_certfile = ssl_keyfile = None
    if settings.public_ui:
        from sqlalchemy import select

        from ostium.db.models import Certificate

        async def _public_ui_totp_ready() -> bool:
            from ostium.services.auth import get_admin

            engine, factory, _store = await _database(settings)
            try:
                async with factory() as session:
                    admin = await get_admin(session)
                return bool(admin is not None and admin.totp_secret_enc)
            finally:
                await engine.dispose()

        if not _run(_public_ui_totp_ready()):
            err_console.print(
                "[yellow]public UI is enabled but TOTP is not configured; "
                "refusing to expose the admin UI[/yellow]"
            )
            raise typer.Exit(code=6)

        async def _find_cert() -> tuple[str, str] | None:
            from ostium.services.settings import get_setting
            from ostium.util.time import as_utc, utcnow

            engine, factory, _store = await _database(settings)
            try:
                async with factory() as session:
                    server_info = await get_setting(session, "server", {})
                    domain = server_info.get("domain") if isinstance(server_info, dict) else None
                    query = select(Certificate).where(
                        Certificate.status == "ready",
                        Certificate.expires_at.is_not(None),
                    )
                    if domain:
                        query = query.where(Certificate.domain == domain)
                    else:
                        query = query.order_by(Certificate.expires_at.desc())
                    certs = (await session.execute(query)).scalars().all()
                now = utcnow()
                cert = next(
                    (
                        item
                        for item in certs
                        if item.expires_at is not None and as_utc(item.expires_at) > now
                    ),
                    None,
                )
                if cert is None:
                    return None
                if not (Path(cert.cert_path).is_file() and Path(cert.key_path).is_file()):
                    return None
                return (cert.cert_path, cert.key_path)
            finally:
                await engine.dispose()

        found = _run(_find_cert())
        if found:
            ssl_certfile, ssl_keyfile = found
        else:
            err_console.print(
                "[yellow]public UI is enabled but no certificate is ready; "
                "refusing to serve HTTP publicly[/yellow]"
            )
            raise typer.Exit(code=6)
    uvicorn.run(
        build_app(settings),
        host=settings.host,
        port=settings.port,
        reload=reload,
        log_level=settings.log_level,
        access_log=False,
        server_header=False,
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
    )


@app.command("core-run")
def core_run() -> None:
    """Run the minimal privileged core service (internal)."""

    from ostium.core.app import run_core

    settings = _load_settings()
    run_core(settings)


@app.command()
def status(json_output: bool = typer.Option(False, "--json")) -> None:
    """Show local service and core status."""

    settings = _load_settings()
    payload: dict[str, Any] = {
        "version": __version__,
        "role": settings.role.value,
        "data_dir": str(settings.data_dir),
        "config_file": str(settings.config_file),
        "database": settings.paths.db_path.is_file(),
        "core_binary": _engine_binary(settings).is_file(),
        "ui_url": f"http://127.0.0.1:{settings.port}",
        "core": None,
    }
    try:
        payload["core"] = _api(settings, "GET", "/api/v1/system/services")["services"][1]
    except SystemExit:
        payload["core"] = {"running": False, "reachable": False}
    if json_output:
        _json(payload)
        return
    console.print(f"[bold]Ostium {__version__}[/bold] ({payload['role']})")
    console.print(f"Data: {payload['data_dir']}")
    console.print(f"UI:   {payload['ui_url']}")
    console.print(f"Core binary: {'yes' if payload['core_binary'] else 'no'}")
    core = payload["core"] or {}
    console.print(f"Core: {'running' if core.get('running') else 'stopped'}")


@app.command()
def open() -> None:  # noqa: A001
    """Open the Web UI in the default browser with a one-time local login."""

    settings = _load_settings()
    from urllib.parse import quote

    from ostium.services.auth import make_local_login_token

    token = make_local_login_token(settings)
    scheme = "https" if settings.public_ui else "http"
    base = f"{scheme}://127.0.0.1:{settings.port}"
    url = f"{base}/api/v1/auth/local-login?token={quote(token)}"
    console.print(base)
    webbrowser.open(url)


@app.command()
def logs(
    follow: bool = typer.Option(False, "-f", "--follow"),
    source: str = typer.Option("ostium", "--source"),
    lines: int = typer.Option(200, "--lines"),
) -> None:
    """Show control-plane or core logs."""

    settings = _load_settings()
    path = settings.paths.logs_dir / ("core.log" if source == "core" else "ostium.log")
    if source == "ostium" and not path.exists():
        if shutil.which("journalctl"):
            os.execvp(  # noqa: S606 - fixed journalctl argv
                "journalctl",
                ["journalctl", "-u", "ostium", "-n", str(lines), "-f" if follow else "--no-pager"],
            )
        _fail("no log file found", 4)
    if not path.is_file():
        _fail(f"log file not found: {path}", 4)
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    console.print("\n".join(content))
    if follow:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(0, os.SEEK_END)
            try:
                while True:
                    line = handle.readline()
                    if line:
                        console.print(line, end="")
                    else:
                        import time

                        time.sleep(0.5)
            except KeyboardInterrupt:
                return


@app.command()
def doctor(
    json_output: bool = typer.Option(False, "--json"),
    fix: bool = typer.Option(False, "--fix"),
) -> None:
    """Run local diagnostics."""

    settings = _load_settings()
    fixes: list[str] = []
    if fix:
        settings.paths.ensure()
        targets = [
            (settings.data_dir, 0o700),
            (settings.paths.runtime_dir, 0o700),
            (settings.paths.logs_dir, 0o700),
            (settings.paths.certs_dir, 0o700),
            (settings.paths.backups_dir, 0o700),
            (settings.paths.master_key_path, 0o600),
            (settings.paths.db_path, 0o600),
            (settings.config_file, 0o600),
        ]
        for path, mode in targets:
            if path.exists():
                try:
                    path.chmod(mode)
                    fixes.append(str(path))
                except OSError:
                    pass
        if not settings.config_file.is_file():
            try:
                settings.save()
                fixes.append(str(settings.config_file))
            except OSError:
                pass
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, message: str) -> None:
        checks.append({"id": name, "status": status, "message": message})

    add("data_dir", "pass" if settings.data_dir.is_dir() else "fail", str(settings.data_dir))
    add(
        "database",
        "pass" if settings.paths.db_path.is_file() else "warn",
        str(settings.paths.db_path),
    )
    add(
        "config",
        "pass" if settings.config_file.is_file() else "warn",
        str(settings.config_file),
    )
    add(
        "core_binary",
        "pass" if _engine_binary(settings).is_file() else "fail",
        str(_engine_binary(settings)),
    )
    try:
        health = httpx.get(f"{settings.core_url}/v1/health", timeout=3, trust_env=False).json()
        add("core_api", "pass" if health.get("status") == "ok" else "warn", json.dumps(health))
    except Exception as exc:
        add("core_api", "fail", str(exc))
    if settings.role is Role.SERVER and not is_loopback_host(settings.host):
        add(
            "bind",
            "warn" if settings.allow_insecure_bind or settings.public_ui else "fail",
            f"admin UI listens on {settings.host}:{settings.port}",
        )
    if json_output:
        _json(
            {
                "checks": checks,
                "fixed": fixes,
                "host_migrated": settings.host_migrated,
            }
        )
    else:
        table = Table(title="Ostium doctor")
        table.add_column("Check")
        table.add_column("Status")
        table.add_column("Detail")
        for check in checks:
            color = {"pass": "green", "warn": "yellow", "fail": "red"}[check["status"]]
            table.add_row(check["id"], f"[{color}]{check['status']}[/{color}]", check["message"])
        console.print(table)
        if fixes:
            console.print(f"[green]fixed {len(fixes)} path/permission issue(s)[/green]")
    if any(check["status"] == "fail" for check in checks):
        raise typer.Exit(code=1)


@app.command("connect")
def connect() -> None:
    """Connect the client using the active profile."""

    settings = _load_settings()
    _api(settings, "POST", "/api/v1/system/connect")
    console.print("[green]connected[/green]")


@app.command("disconnect")
def disconnect() -> None:
    """Stop the client tunnel and restore system settings."""

    settings = _load_settings()
    _api(settings, "POST", "/api/v1/system/disconnect")
    console.print("[green]disconnected[/green]")


@app.command()
def proxy(
    action: str = typer.Argument("status", help="on, off or status"),
) -> None:
    """Enable, disable or inspect the operating-system proxy."""

    settings = _load_settings()
    from ostium.system.proxy import ProxyError, system_proxy

    manager = system_proxy(settings)
    try:
        if action == "on":
            if settings.tun_enabled:
                _fail("TUN mode is enabled; disable it before using the system proxy", 5)
            _client_apply(settings)
            result = manager.enable("127.0.0.1", settings.mixed_port)
            settings.mode = Mode.SYSTEM_PROXY
            try:
                settings.save()
            except OSError:
                pass
        elif action == "off":
            result = manager.disable()
            settings.mode = Mode.MIXED
            try:
                settings.save()
            except OSError:
                pass
        else:
            result = manager.status()
    except ProxyError as exc:
        _fail(str(exc), 5)
    _json(result)


@app.command()
def tun(action: str = typer.Argument("status", help="on, off or status")) -> None:
    """Toggle or inspect TUN mode through the local service."""

    settings = _load_settings()
    if action == "status":
        _json(_api(settings, "GET", "/api/v1/system/info"))
    elif action in {"on", "off"}:
        result = _api(settings, "POST", "/api/v1/system/tun", json={"enabled": action == "on"})
        _json(result)
    else:
        _fail("action must be on, off or status", 2)


def _update_channel(settings: Settings) -> str:
    """Read the operational update channel without making the check brittle."""

    async def _read() -> str:
        from ostium.services.settings import get_setting

        engine, factory, _store = await _database(settings)
        try:
            async with factory() as session:
                value = await get_setting(session, "update_channel", "stable")
                return value if value in {"stable", "beta"} else "stable"
        finally:
            await engine.dispose()

    try:
        result = _run(_read())
        return result if isinstance(result, str) else "stable"
    except Exception:
        return "stable"


@app.command()
def update(check: bool = typer.Option(False, "--check")) -> None:
    """Check for updates (installation is explicit)."""

    console.print(f"Current version: {__version__}")
    if not check:
        console.print(
            "Automatic updates are disabled by design. "
            "Download a signed release from GitHub and install it."
        )
        return
    from packaging.version import InvalidVersion, Version

    settings = _load_settings()
    channel = _update_channel(settings)
    if channel == "beta":
        url = "https://api.github.com/repos/ThzxxArt/Ostium/releases?per_page=30"
    else:
        url = "https://api.github.com/repos/ThzxxArt/Ostium/releases/latest"
    try:
        response = httpx.get(
            url,
            timeout=15,
            follow_redirects=True,
            trust_env=False,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "Ostium"},
        )
        response.raise_for_status()
        payload = response.json()
        if channel == "beta":
            releases = payload if isinstance(payload, list) else []
            versions = []
            for release in releases:
                if not isinstance(release, dict) or release.get("draft"):
                    continue
                try:
                    versions.append(
                        (Version(str(release.get("tag_name", "")).lstrip("v")), release)
                    )
                except InvalidVersion:
                    continue
            if not versions:
                _fail("the update check returned no usable release tag", 4)
            version, selected = max(versions, key=lambda item: item[0])
            latest = str(version)
        else:
            latest = str(payload.get("tag_name", "")).lstrip("v")
            selected = payload
            if not latest:
                _fail("the update check returned no release tag", 4)
        if Version(latest) > Version(__version__):
            console.print(f"[yellow]update available: {latest}[/yellow]")
            console.print(
                str(selected.get("html_url", "https://github.com/ThzxxArt/Ostium/releases"))
            )
        else:
            console.print("[green]Ostium is up to date.[/green]")
    except (httpx.HTTPError, ValueError, InvalidVersion) as exc:
        _fail(f"update check failed: {exc}", 4)


@app.command("diagnostics")
def diagnostics_export(
    action: str = typer.Argument("export", help="export"),
    output: Path = typer.Option(Path("ostium-diagnostics.tar.gz"), "--output"),
) -> None:
    """Export a redacted diagnostics bundle."""

    if action != "export":
        _fail("only the 'export' action is supported", 2)
    settings = _load_settings()
    from ostium.util.redact import redact
    from ostium.util.time import iso, utcnow

    payload = {
        "version": __version__,
        "role": settings.role.value,
        "generated_at": iso(utcnow()),
        "platform": platform.platform(),
        "python": sys.version,
        "data_dir": str(settings.data_dir),
        "config_file": str(settings.config_file),
        "database_exists": settings.paths.db_path.is_file(),
        "core_binary_exists": _engine_binary(settings).is_file(),
        "host": settings.host,
        "port": settings.port,
        "public_ui": settings.public_ui,
        "allow_insecure_bind": settings.allow_insecure_bind,
    }
    doctor_payload: dict[str, Any] = {"checks": []}
    try:
        health = httpx.get(f"{settings.core_url}/v1/health", timeout=3, trust_env=False).json()
        doctor_payload["core_health"] = health
    except Exception as exc:
        doctor_payload["core_health"] = {"error": redact(str(exc))}
    config_text = ""
    if settings.config_file.is_file():
        config_text = redact(settings.config_file.read_text(encoding="utf-8", errors="replace"))
    log_text = ""
    log_path = settings.paths.logs_dir / "ostium.log"
    if log_path.is_file():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]
        log_text = redact("\n".join(lines))
    with tarfile.open(output, "w:gz") as archive:
        import io

        entries = {
            "ostium-diagnostics.json": json.dumps(payload, indent=2),
            "doctor.json": json.dumps(doctor_payload, indent=2),
            "config.redacted.toml": config_text,
            "ostium.log.tail": log_text,
        }
        for name, content in entries.items():
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(data))
    if os.name == "posix":
        try:
            output.chmod(0o600)
        except OSError:
            pass
    console.print(f"wrote {output}")


def _apply_failure(message: str) -> None:
    if _ALLOW_DEGRADED:
        err_console.print(
            f"[yellow]configuration saved but not applied (--allow-degraded): {message}[/yellow]"
        )
        return
    _fail(f"configuration saved but not applied: {message}", 3)


def _server_apply(settings: Settings) -> None:
    from ostium.engine.manager import EngineError, EngineManager
    from ostium.services.events import EventBus

    async def _apply() -> None:
        engine, factory, store = await _database(settings)
        try:
            manager = EngineManager(settings, factory, store, EventBus())
            async with factory() as session:
                try:
                    await manager.apply_server(session)
                    await session.commit()
                    console.print("[green]configuration applied[/green]")
                except EngineError as exc:
                    await session.rollback()
                    _apply_failure(str(exc))
        finally:
            await engine.dispose()

    _run(_apply())


def _client_apply(settings: Settings) -> None:
    from ostium.engine.manager import EngineError, EngineManager
    from ostium.services.events import EventBus

    async def _apply() -> None:
        engine, factory, store = await _database(settings)
        try:
            manager = EngineManager(settings, factory, store, EventBus())
            async with factory() as session:
                try:
                    await manager.apply_client(session)
                    await session.commit()
                    console.print("[green]client configuration applied[/green]")
                except EngineError as exc:
                    await session.rollback()
                    _apply_failure(str(exc))
        finally:
            await engine.dispose()

    _run(_apply())


# --------------------------------------------------------------------------- users


def _user_rows(settings: Settings) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from ostium.db.models import ProxyUser
    from ostium.services.users import serialize_user

    async def _list() -> list[dict[str, Any]]:
        engine, factory, _store = await _database(settings)
        async with factory() as session:
            rows = (
                (await session.execute(select(ProxyUser).order_by(ProxyUser.created_at)))
                .scalars()
                .all()
            )
            data = [serialize_user(row) for row in rows]
        await engine.dispose()
        return data

    return cast(list[dict[str, Any]], _run(_list()))


@user_app.command("list")
def user_list(json_output: bool = typer.Option(False, "--json")) -> None:
    """List proxy users."""

    settings = _load_settings()
    rows = _user_rows(settings)
    if json_output:
        _json(rows)
        return
    table = Table(title="Ostium users")
    for column in ("Name", "Status", "Used", "Quota", "Expires"):
        table.add_column(column)
    for row in rows:
        table.add_row(
            row["name"],
            row["status"],
            _human_bytes(row["used_bytes"]),
            _human_bytes(row["quota_bytes"]) if row["quota_bytes"] else "unlimited",
            row["expires_at"] or "never",
        )
    console.print(table)


@user_app.command("add")
def user_add(
    name: str = typer.Argument(...),
    quota: str | None = typer.Option(None, "--quota", help="e.g. 50G, 500M"),
    cycle: str = typer.Option("total", "--cycle"),
    expires: str | None = typer.Option(None, "--expires", help="ISO date/time"),
    note: str = typer.Option("", "--note"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Add a proxy user and print the subscription token once."""

    from datetime import datetime

    settings = _load_settings()

    async def _add() -> dict[str, Any]:
        engine, factory, store = await _database(settings)
        result: dict[str, Any] = {}
        try:
            from ostium.services.users import create_user

            async with factory() as session:
                user, _password, token = await create_user(
                    session,
                    store,
                    name=name,
                    quota_bytes=_parse_bytes(quota) if quota else 0,
                    quota_cycle=cycle,
                    expires_at=datetime.fromisoformat(expires) if expires else None,
                    note=note,
                )
                await _audit(
                    session,
                    "user.created",
                    user.name,
                    quota_bytes=user.quota_bytes,
                    quota_cycle=user.quota_cycle,
                )
                await session.commit()
                result = {"user": user.name, "token": token, "id": user.id}
        finally:
            await engine.dispose()
        return result

    result = _run(_add())
    # The subscription token is revealed exactly once.  Print it before the
    # core apply: an unavailable core must not destroy the only copy of the
    # credential and force the operator to rotate the user immediately.
    if json_output:
        _json(result)
    else:
        console.print(f"[green]user {result['user']} created[/green]")
        console.print(f"subscription token: [bold]{result['token']}[/bold] (shown once)")
    _server_apply(settings)


@user_app.command("show")
def user_show(name: str, json_output: bool = typer.Option(False, "--json")) -> None:
    """Show one user."""

    settings = _load_settings()
    rows = [row for row in _user_rows(settings) if row["name"] == name]
    if not rows:
        _fail("user not found", 1)
    _json(rows[0]) if json_output else console.print_json(json.dumps(rows[0], default=str))


@user_app.command("disable")
def user_disable(name: str) -> None:
    """Disable a user."""

    _set_user_enabled(name, False)


@user_app.command("enable")
def user_enable(name: str) -> None:
    """Enable a user."""

    _set_user_enabled(name, True)


def _set_user_enabled(name: str, enabled: bool) -> None:
    from sqlalchemy import select

    from ostium.db.models import ProxyUser

    settings = _load_settings()

    async def _set() -> None:
        engine, factory, _store = await _database(settings)
        try:
            async with factory() as session:
                user = (
                    await session.execute(select(ProxyUser).where(ProxyUser.name == name))
                ).scalar_one_or_none()
                if user is None:
                    _fail("user not found", 1)
                user.enabled = enabled
                if enabled:
                    user.disabled_reason = None
                await _audit(session, "user.enabled" if enabled else "user.disabled", name)
                await session.commit()
        finally:
            await engine.dispose()

    _run(_set())
    _server_apply(settings)
    console.print(f"{'enabled' if enabled else 'disabled'} {name}")


@user_app.command("rotate")
def user_rotate(name: str, subscription: bool = typer.Option(False, "--subscription")) -> None:
    """Rotate a user's credentials."""

    from sqlalchemy import select

    from ostium.db.models import ProxyUser
    from ostium.services.users import rotate_credentials, rotate_subscription

    settings = _load_settings()

    async def _rotate() -> str | None:
        engine, factory, store = await _database(settings)
        try:
            async with factory() as session:
                user = (
                    await session.execute(select(ProxyUser).where(ProxyUser.name == name))
                ).scalar_one_or_none()
                if user is None:
                    _fail("user not found", 1)
                await rotate_credentials(session, store, user)
                token = await rotate_subscription(session, store, user) if subscription else None
                await _audit(
                    session, "user.credentials_rotated", name, subscription=bool(subscription)
                )
                await session.commit()
        finally:
            await engine.dispose()
        return token

    token = _run(_rotate())
    console.print(f"credentials rotated for {name}")
    if token:
        # Never lose the one-time token if the core cannot apply immediately.
        console.print(f"new subscription token: {token}")
    _server_apply(settings)


@user_app.command("remove")
def user_remove(name: str, yes: bool = typer.Option(False, "--yes")) -> None:
    """Delete a user."""

    from sqlalchemy import select

    from ostium.db.models import ProxyUser

    if not yes:
        typer.confirm(f"delete user {name}?", abort=True)
    settings = _load_settings()

    async def _remove() -> None:
        engine, factory, _store = await _database(settings)
        try:
            async with factory() as session:
                user = (
                    await session.execute(select(ProxyUser).where(ProxyUser.name == name))
                ).scalar_one_or_none()
                if user is None:
                    _fail("user not found", 1)
                await session.delete(user)
                await _audit(session, "user.deleted", name)
                await session.commit()
        finally:
            await engine.dispose()

    _run(_remove())
    _server_apply(settings)
    console.print(f"deleted {name}")


@user_app.command("quota")
def user_quota(
    name: str,
    quota: str = typer.Option(..., "--quota"),
    cycle: str = typer.Option("total", "--cycle"),
) -> None:
    """Set a user's quota."""

    if cycle not in {"total", "monthly"}:
        _fail("--cycle must be total or monthly", 2)
    from sqlalchemy import select

    from ostium.db.models import ProxyUser

    settings = _load_settings()

    async def _quota() -> None:
        engine, factory, _store = await _database(settings)
        try:
            async with factory() as session:
                user = (
                    await session.execute(select(ProxyUser).where(ProxyUser.name == name))
                ).scalar_one_or_none()
                if user is None:
                    _fail("user not found", 1)
                user.quota_bytes = _parse_bytes(quota)
                user.quota_cycle = cycle
                await _audit(session, "user.quota_updated", name, quota=quota, cycle=cycle)
                await session.commit()
        finally:
            await engine.dispose()

    _run(_quota())
    _server_apply(settings)
    console.print(f"quota updated for {name}")


@user_app.command("subscription")
def user_subscription(name: str, rotate: bool = typer.Option(False, "--rotate")) -> None:
    """Print a user's subscription information."""

    from sqlalchemy import select

    from ostium.db.models import ProxyUser
    from ostium.services.users import (
        decrypt_subscription_token,
        rotate_subscription,
        server_hostname,
    )

    settings = _load_settings()

    async def _sub() -> dict[str, Any]:
        engine, factory, store = await _database(settings)
        data: dict[str, Any] = {}
        try:
            async with factory() as session:
                user = (
                    await session.execute(select(ProxyUser).where(ProxyUser.name == name))
                ).scalar_one_or_none()
                if user is None:
                    _fail("user not found", 1)
                token = (
                    await rotate_subscription(session, store, user)
                    if rotate
                    else decrypt_subscription_token(user, store)
                )
                if token is None:
                    token = await rotate_subscription(session, store, user)
                host = await server_hostname(session)
                from ostium.services.public_url import public_base_url

                base = await public_base_url(session, settings)
                await _audit(session, "user.subscription_viewed", user.name)
                await session.commit()
                data = {
                    "token": token,
                    "host": host,
                    "base_url": base,
                    "formats": {
                        fmt: f"{base}/sub/{token}?format={fmt}"
                        for fmt in ("ostium", "base64", "clash", "singbox")
                    },
                }
        finally:
            await engine.dispose()
        return data

    _json(_run(_sub()))


@user_app.command("export")
def user_export(
    name: str, output: Path = typer.Option(Path("ostium-profile.json"), "--output")
) -> None:
    """Export an Ostium Profile v1 document."""

    from sqlalchemy import select

    from ostium.db.models import ProxyUser
    from ostium.services.subscriptions import render_subscription

    settings = _load_settings()

    async def _export() -> str:
        engine, factory, store = await _database(settings)
        async with factory() as session:
            user = (
                await session.execute(select(ProxyUser).where(ProxyUser.name == name))
            ).scalar_one_or_none()
            if user is None:
                _fail("user not found", 1)
            content, _ = await render_subscription(session, store, user, "ostium")
        await engine.dispose()
        return content

    output.write_text(_run(_export()), encoding="utf-8")
    if os.name == "posix":
        try:
            output.chmod(0o600)
        except OSError:
            pass
    console.print(f"wrote {output}")


def _human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"


@profile_app.command("list")
def profile_list(json_output: bool = typer.Option(False, "--json")) -> None:
    """List client profiles."""

    from sqlalchemy import select

    from ostium.db.models import Profile
    from ostium.services.profiles import serialize_profile

    settings = _load_settings()

    async def _list() -> list[dict[str, Any]]:
        engine, factory, store = await _database(settings)
        async with factory() as session:
            rows = (
                (await session.execute(select(Profile).order_by(Profile.sort_order)))
                .scalars()
                .all()
            )
            data = [serialize_profile(row, store) for row in rows]
        await engine.dispose()
        return data

    data = _run(_list())
    if json_output:
        _json(data)
        return
    table = Table(title="Client profiles")
    table.add_column("Name")
    table.add_column("Kind")
    table.add_column("Endpoints")
    table.add_column("Refreshed")
    for row in data:
        table.add_row(
            row["name"],
            row["kind"],
            str(len(row["endpoints"])),
            str(row["last_refresh_at"] or "never"),
        )
    console.print(table)


@profile_app.command("import")
def profile_import(
    source: str = typer.Argument(..., help="file path, URL, or literal URI"),
    name: str = typer.Option("Imported", "--name"),
) -> None:
    """Import a profile from a file, URL or share link."""

    from ostium.services.profiles import create_profile, parse_subscription_text

    settings = _load_settings()
    text: str
    subscription_url: str | None = None
    if source.startswith(("http://", "https://")):
        from ostium.services.netguard import UnsafeUrlError, fetch_limited
        from ostium.services.profiles import MAX_SUBSCRIPTION_BYTES

        subscription_url = source
        try:
            fetched = _run(
                fetch_limited(
                    source,
                    allow_private=True,
                    max_bytes=MAX_SUBSCRIPTION_BYTES,
                    timeout=20.0,
                    headers={"User-Agent": "Ostium/0.1"},
                )
            )
        except UnsafeUrlError as exc:
            _fail(str(exc), 2)
        except (httpx.HTTPError, ValueError) as exc:
            _fail(f"subscription download failed: {exc}", 1)
        if fetched.status_code >= 400:
            _fail(f"subscription download failed: HTTP {fetched.status_code}", 1)
        text = fetched.text
    else:
        path = Path(source)
        text = path.read_text(encoding="utf-8") if path.is_file() else source

    async def _import() -> int:
        engine, factory, store = await _database(settings)
        endpoints: list[Any] = []
        try:
            async with factory() as session:
                endpoints = parse_subscription_text(text)
                profile = await create_profile(
                    session,
                    store,
                    name=name,
                    endpoints=endpoints,
                    kind="subscription" if subscription_url else "manual",
                    subscription_url=subscription_url,
                )
                await _audit(
                    session,
                    "profile.created",
                    profile.name,
                    endpoints=len(endpoints),
                    subscription=bool(subscription_url),
                )
                await session.commit()
        finally:
            await engine.dispose()
        return len(endpoints)

    count = _run(_import())
    _client_apply(settings)
    console.print(f"imported {count} endpoint(s) into {name}")


@profile_app.command("remove")
def profile_remove(name: str, yes: bool = typer.Option(False, "--yes")) -> None:
    """Remove a client profile."""

    from sqlalchemy import select

    from ostium.db.models import Profile

    if not yes:
        typer.confirm(f"delete profile {name}?", abort=True)
    settings = _load_settings()

    async def _remove() -> None:
        from ostium.services.settings import get_setting, set_setting

        engine, factory, _store = await _database(settings)
        try:
            async with factory() as session:
                profiles = (
                    (await session.execute(select(Profile).where(Profile.name == name)))
                    .scalars()
                    .all()
                )
                if not profiles:
                    _fail("profile not found", 1)
                if len(profiles) > 1:
                    _fail(
                        f"multiple profiles are named {name!r}; remove them from the Web UI "
                        "or rename one first",
                        2,
                    )
                profile = profiles[0]
                if await get_setting(session, "active_profile_id") == profile.id:
                    await set_setting(session, "active_profile_id", None)
                await session.delete(profile)
                await _audit(session, "profile.deleted", name)
                await session.commit()
        finally:
            await engine.dispose()

    _run(_remove())
    _client_apply(settings)
    console.print(f"deleted {name}")


@profile_app.command("refresh")
def profile_refresh(name: str) -> None:
    """Refresh a subscription-backed profile."""

    from sqlalchemy import select

    from ostium.db.models import Profile
    from ostium.services.profiles import refresh_profile

    settings = _load_settings()

    async def _refresh() -> int:
        engine, factory, store = await _database(settings)
        count = 0
        try:
            async with factory() as session:
                profiles = (
                    (await session.execute(select(Profile).where(Profile.name == name)))
                    .scalars()
                    .all()
                )
                if not profiles:
                    _fail("profile not found", 1)
                if len(profiles) > 1:
                    _fail(
                        f"multiple profiles are named {name!r}; refresh them from the Web UI "
                        "or rename one first",
                        2,
                    )
                count = await refresh_profile(session, store, profiles[0])
                await _audit(session, "profile.refreshed", name, endpoints=count)
                await session.commit()
        finally:
            await engine.dispose()
        return count

    count = _run(_refresh())
    _client_apply(settings)
    console.print(f"refreshed {count} endpoint(s)")


# ----------------------------------------------------------------------------- core


@core_app.command("status")
def core_status() -> None:
    """Show core service status."""

    settings = _load_settings()
    try:
        _json(httpx.get(f"{settings.core_url}/v1/health", timeout=3, trust_env=False).json())
    except httpx.HTTPError as exc:
        _fail(f"core is not reachable: {exc}", 4)


@core_app.command("version")
def core_version() -> None:
    """Print the installed sing-box version."""

    settings = _load_settings()
    binary = _engine_binary(settings)
    if not binary.is_file():
        _fail(f"core binary not found at {binary}", 6)
    import subprocess

    result = subprocess.run([str(binary), "version"], capture_output=True, text=True, check=False)
    console.print(result.stdout or result.stderr)


@core_app.command("install")
def core_install(
    binary: Path | None = typer.Option(None, "--binary", help="Path to a sing-box binary"),
    url: str | None = typer.Option(None, "--url"),
    sha256: str | None = typer.Option(None, "--sha256"),
    manifest: str | None = typer.Option(
        None, "--manifest", help="Manifest file or URL from an Ostium release"
    ),
    version: str | None = typer.Option(None, "--version", help="Pin a manifest version"),
) -> None:
    """Install the core binary (copy, verified download, or release manifest)."""

    import hashlib
    import tempfile

    settings = _load_settings()
    target = _engine_binary(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = target.read_bytes() if target.is_file() else None

    def _restore_previous() -> None:
        if previous is not None:
            target.write_bytes(previous)
            if os.name == "posix":
                target.chmod(0o755)
        else:
            target.unlink(missing_ok=True)

    if manifest:
        try:
            if manifest.startswith(("http://", "https://")):
                if not manifest.startswith("https://"):
                    _fail("core manifest URLs must use HTTPS", 6)
                response = httpx.get(manifest, timeout=30, follow_redirects=True, trust_env=False)
                if response.url.scheme != "https":
                    _fail("core manifest redirect must stay on HTTPS", 6)
                response.raise_for_status()
                data = response.json()
            else:
                data = json.loads(Path(manifest).read_text(encoding="utf-8"))
        except typer.Exit:
            raise
        except Exception as exc:
            _fail(f"could not read core manifest: {exc}", 6)
        os_name = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}.get(
            platform.system(), platform.system().lower()
        )
        machine = platform.machine().lower()
        if machine in {"aarch64", "arm64"}:
            arch = "arm64"
        elif machine in {"x86_64", "amd64"}:
            arch = "amd64"
        else:
            _fail(f"unsupported CPU architecture: {machine}", 6)
        candidates = [
            item
            for item in data.get("artifacts", [])
            if item.get("os") == os_name and item.get("arch") == arch
        ]
        if version:
            candidates = [item for item in candidates if item.get("version") == version]
        if not candidates:
            _fail(f"no core artifact for {os_name}/{arch} in the manifest", 6)
        from packaging.version import InvalidVersion, Version

        def _version_key(item: dict[str, Any]) -> Version:
            try:
                return Version(str(item.get("version", "0")))
            except InvalidVersion:
                return Version("0")

        artifact = max(candidates, key=_version_key)
        artifact_url = str(artifact["url"])
        if not artifact_url.startswith("https://"):
            _fail("core manifest artifact URL must use HTTPS", 6)
        response = httpx.get(artifact_url, timeout=180, follow_redirects=True, trust_env=False)
        response.raise_for_status()
        digest = hashlib.sha256(response.content).hexdigest()
        if digest != artifact["sha256"]:
            _fail("SHA256 mismatch; refusing to install", 6)
        attestation = artifact.get("attestation") or artifact.get("attestation_sha256")
        if isinstance(attestation, dict):
            attestation_url = str(attestation.get("url", ""))
            expected_attestation = str(attestation.get("sha256", ""))
            if attestation_url and expected_attestation:
                if not attestation_url.startswith("https://"):
                    _fail("attestation URL must use HTTPS", 6)
                proof = httpx.get(
                    attestation_url, timeout=30, follow_redirects=True, trust_env=False
                )
                proof.raise_for_status()
                if hashlib.sha256(proof.content).hexdigest() != expected_attestation:
                    _fail("attestation digest mismatch; refusing to install", 6)
        with tempfile.TemporaryDirectory(prefix="ostium-core-") as temp:
            archive_path = Path(temp) / "core.tar.gz"
            archive_path.write_bytes(response.content)
            with tarfile.open(archive_path, "r:gz") as archive:
                member = next(
                    (
                        item
                        for item in archive.getmembers()
                        if Path(item.name).name in {"sing-box", "sing-box.exe"}
                    ),
                    None,
                )
                if member is None:
                    _fail("manifest archive does not contain sing-box", 6)
                assert member is not None
                member.name = Path(member.name).name
                extracted = Path(temp) / member.name
                archive.extract(member, Path(temp), filter="data")
            shutil.copy2(extracted, target)
    elif binary:
        shutil.copy2(binary, target)
    elif url:
        if not url.startswith("https://"):
            _fail("--url must use HTTPS; download the file and use --binary for HTTP mirrors", 2)
        if not sha256:
            _fail("--sha256 is required when downloading a core with --url", 2)
        response = httpx.get(url, timeout=120, follow_redirects=True, trust_env=False)
        response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != sha256:
            _fail("SHA256 mismatch; refusing to install", 6)
        if url.split("?", 1)[0].endswith((".tar.gz", ".tgz")):
            import io

            with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
                member = next(
                    (
                        item
                        for item in archive.getmembers()
                        if Path(item.name).name in {"sing-box", "sing-box.exe"}
                    ),
                    None,
                )
                if member is None:
                    _fail("core archive does not contain sing-box", 6)
                assert member is not None
                member.name = Path(member.name).name
                with tempfile.TemporaryDirectory(prefix="ostium-core-") as temp:
                    archive.extract(member, Path(temp), filter="data")
                    target.write_bytes((Path(temp) / member.name).read_bytes())
        else:
            target.write_bytes(response.content)
    else:
        _fail("provide --binary, --url or --manifest", 2)
    if os.name == "posix":
        target.chmod(0o755)
    import subprocess

    try:
        probe = subprocess.run(
            [str(target), "version"], capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _restore_previous()
        _fail(f"installed core could not be executed: {exc}", 6)
    if probe.returncode != 0:
        _restore_previous()
        _fail(f"installed core failed its version check: {probe.stderr.strip()}", 6)
    console.print(f"installed core at {target}")
    console.print(
        probe.stdout.strip().splitlines()[0] if probe.stdout.strip() else "core is runnable"
    )


@core_app.command("update")
def core_update(
    manifest: str = typer.Option(
        "https://github.com/ThzxxArt/Ostium/releases/latest/download/core-manifest.json",
        "--manifest",
    ),
    version: str | None = typer.Option(None, "--version"),
) -> None:
    """Install the latest pinned core from the release manifest."""

    core_install(None, None, None, manifest, version)


# --------------------------------------------------------------------------- backup


@backup_app.command("create")
def backup_create(
    password: str | None = typer.Option(None, "--password", help="Encrypt with this password"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Create a backup."""

    from ostium.services.backup import create_backup

    settings = _load_settings()
    if not password:
        err_console.print(
            "[yellow]warning: an unencrypted backup contains master.key and the full "
            "database; store it on encrypted media or pass --password.[/yellow]"
        )
    result = create_backup(settings, password=password, target=output)
    _audit_sync(
        settings,
        "backup.created",
        str(result.get("filename")),
        encrypted=bool(result.get("encrypted")),
    )
    console.print_json(json.dumps(result))


@backup_app.command("list")
def backup_list() -> None:
    """List backup files."""

    settings = _load_settings()
    for pattern in ("ostium-backup-*", "ostium-auto-backup-*"):
        for path in sorted(settings.paths.backups_dir.glob(pattern)):
            console.print(f"{path.name}  {path.stat().st_size} bytes")


@backup_app.command("restore")
def backup_restore(
    path: Path,
    password: str | None = typer.Option(None, "--password"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Restore a backup (stop both services first)."""

    from ostium.services.backup import restore_backup

    if not yes:
        typer.confirm(
            "restore will replace the current database and certificates; continue?", abort=True
        )
    settings = _load_settings()
    result = restore_backup(settings, path, password=password)
    _audit_sync(settings, "backup.restored", path.name)
    console.print_json(json.dumps(result))


# ------------------------------------------------------------------------- certificates


@cert_app.command("list")
def cert_list() -> None:
    """List certificates."""

    from sqlalchemy import select

    from ostium.db.models import Certificate
    from ostium.services.certificates import serialize_certificate

    settings = _load_settings()

    async def _list() -> list[dict[str, Any]]:
        engine, factory, _store = await _database(settings)
        async with factory() as session:
            rows = (await session.execute(select(Certificate))).scalars().all()
            data = [serialize_certificate(row) for row in rows]
        await engine.dispose()
        return data

    _json(_run(_list()))


@cert_app.command("issue")
def cert_issue(domain: str, self_signed: bool = typer.Option(False, "--self-signed")) -> None:
    """Issue an ACME or self-signed certificate."""

    from ostium.services.certificates import create_self_signed

    settings = _load_settings()
    if not self_signed:
        _fail(
            "interactive ACME issuance is available from the Web UI; "
            "use --self-signed for local testing",
            2,
        )

    async def _issue() -> dict[str, Any]:
        engine, factory, _store = await _database(settings)
        async with factory() as session:
            cert = await create_self_signed(session, settings, domain=domain)
            await _audit(session, "certificate.self_signed", cert.domain)
            await session.commit()
            result = {
                "domain": cert.domain,
                "expires_at": cert.expires_at.isoformat() if cert.expires_at else None,
            }
        await engine.dispose()
        return result

    _json(_run(_issue()))


# ---------------------------------------------------------------------------- install


@service_app.command("install")
def service_install() -> None:
    """Install systemd units (Linux, root)."""

    if sys.platform != "linux":
        _fail("systemd installation is only supported on Linux", 5)
    if os.geteuid() != 0:
        _fail("run as root (sudo ostium service install)", 5)
    root = Path(__file__).resolve().parents[3]
    source = root / "deploy" / "systemd"
    if not source.is_dir():
        _fail(
            "systemd unit templates are not bundled in this installation; "
            "use the release installer",
            1,
        )
    for unit in source.glob("*.service"):
        shutil.copy2(unit, Path("/etc/systemd/system") / unit.name)
    import subprocess

    result = subprocess.run(
        ["systemctl", "daemon-reload"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        _fail(f"systemctl daemon-reload failed: {result.stderr.strip()}", 5)
    console.print("systemd units installed; enable with systemctl enable --now ostium-core ostium")


@service_app.command("uninstall")
def service_uninstall() -> None:
    """Remove systemd units (Linux, root)."""

    if sys.platform != "linux" or os.geteuid() != 0:
        _fail("run as root on Linux", 5)
    for name in ("ostium.service", "ostium-core.service"):
        Path("/etc/systemd/system", name).unlink(missing_ok=True)
    import subprocess

    result = subprocess.run(
        ["systemctl", "daemon-reload"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        _fail(f"systemctl daemon-reload failed: {result.stderr.strip()}", 5)
    console.print("systemd units removed (data is preserved)")


def _parse_bytes(value: str) -> int:
    value = value.strip().upper()
    units = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    if value[-1] in units:
        return int(float(value[:-1]) * units[value[-1]])
    return int(value)


if __name__ == "__main__":
    app()
