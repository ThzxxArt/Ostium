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
from typing import Any, cast

import httpx
import typer
from rich.console import Console
from rich.table import Table

from ostium import __version__
from ostium.config import Role, Settings
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


def _load_settings() -> Settings:
    return Settings.load()


def _json(value: Any) -> None:
    console.print_json(json.dumps(value, ensure_ascii=False, default=str))


async def _database(settings: Settings) -> tuple[Any, Any, SecretStore]:
    engine = create_engine(settings.paths.db_path)
    await create_schema(engine)
    factory = create_session_factory(engine)
    store = SecretStore.from_data_dir(settings.data_dir)
    return engine, factory, store


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _fail(message: str, code: int = 1) -> None:
    err_console.print(f"[red]error:[/red] {message}")
    raise typer.Exit(code)


def _base_url(settings: Settings) -> str:
    return f"http://127.0.0.1:{settings.port}"


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
    if config_dir:
        settings.config_dir = config_dir
        settings.config_path = config_dir / "config.toml"
    settings.role = role_value
    settings.dev = dev
    settings.host = host or (
        "127.0.0.1" if dev else ("0.0.0.0" if role_value is Role.SERVER else "127.0.0.1")
    )
    settings.port = port or (8443 if role_value is Role.SERVER else 8787)
    settings.public_ui = public_ui and role_value is Role.SERVER
    if role_value is Role.SERVER or settings.dev:
        settings.core_token_file = settings.data_dir / "runtime" / "core.token"
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
                await set_setting(
                    session,
                    "server",
                    {
                        "domain": domain,
                        "public_host": domain,
                        "public_ui": settings.public_ui,
                    },
                )
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
    with contextlib.suppress(Exception):
        result = apply_pending_restore(settings)
        if result:
            console.print("[green]Staged backup restored before startup.[/green]")
    ssl_certfile = ssl_keyfile = None
    if settings.public_ui:
        from sqlalchemy import select

        from ostium.db.models import Certificate

        async def _find_cert() -> tuple[str, str] | None:
            from ostium.services.settings import get_setting

            engine, factory, _store = await _database(settings)
            async with factory() as session:
                server_info = await get_setting(session, "server", {})
                domain = server_info.get("domain") if isinstance(server_info, dict) else None
                query = select(Certificate).where(Certificate.status == "ready")
                if domain:
                    query = query.where(Certificate.domain == domain)
                else:
                    query = query.order_by(Certificate.expires_at.desc())
                cert = (await session.execute(query)).scalars().first()
            await engine.dispose()
            return (cert.cert_path, cert.key_path) if cert else None

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
        "core_binary": settings.paths.engine_binary.is_file(),
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
    url = f"http://127.0.0.1:{settings.port}/api/v1/auth/local-login?token={quote(token)}"
    console.print(f"http://127.0.0.1:{settings.port}")
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
        "pass" if settings.paths.engine_binary.is_file() else "fail",
        str(settings.paths.engine_binary),
    )
    try:
        health = httpx.get(f"{settings.core_url}/v1/health", timeout=3, trust_env=False).json()
        add("core_api", "pass" if health.get("status") == "ok" else "warn", json.dumps(health))
    except Exception as exc:
        add("core_api", "fail", str(exc))
    if json_output:
        _json({"checks": checks})
    else:
        table = Table(title="Ostium doctor")
        table.add_column("Check")
        table.add_column("Status")
        table.add_column("Detail")
        for check in checks:
            color = {"pass": "green", "warn": "yellow", "fail": "red"}[check["status"]]
            table.add_row(check["id"], f"[{color}]{check['status']}[/{color}]", check["message"])
        console.print(table)
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
            result = manager.enable("127.0.0.1", settings.mixed_port)
        elif action == "off":
            result = manager.disable()
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


@app.command()
def update(check: bool = typer.Option(False, "--check")) -> None:
    """Check for updates (installation is explicit)."""

    console.print(f"Current version: {__version__}")
    console.print(
        "Automatic updates are disabled by design. "
        "Download a signed release from GitHub and install it."
    )


@app.command("diagnostics")
def diagnostics_export(
    action: str = typer.Argument("export", help="export"),
    output: Path = typer.Option(Path("ostium-diagnostics.tar.gz"), "--output"),
) -> None:
    """Export a redacted diagnostics bundle."""

    if action != "export":
        _fail("only the 'export' action is supported", 2)
    settings = _load_settings()
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
        "core_binary_exists": settings.paths.engine_binary.is_file(),
    }
    with tarfile.open(output, "w:gz") as archive:
        import io

        data = json.dumps(payload, indent=2).encode()
        info = tarfile.TarInfo("ostium-diagnostics.json")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    console.print(f"wrote {output}")


def _server_apply(settings: Settings) -> None:
    from ostium.engine.manager import EngineError, EngineManager
    from ostium.services.events import EventBus

    async def _apply() -> None:
        engine, factory, store = await _database(settings)
        manager = EngineManager(settings, factory, store, EventBus())
        async with factory() as session:
            try:
                await manager.apply_server(session)
                await session.commit()
                console.print("[green]configuration applied[/green]")
            except EngineError as exc:
                err_console.print(f"[yellow]configuration saved but not applied: {exc}[/yellow]")
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
            await session.commit()
            result = {"user": user.name, "token": token, "id": user.id}
        await engine.dispose()
        return result

    result = _run(_add())
    _server_apply(settings)
    if json_output:
        _json(result)
    else:
        console.print(f"[green]user {result['user']} created[/green]")
        console.print(f"subscription token: [bold]{result['token']}[/bold] (shown once)")


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
        async with factory() as session:
            user = (
                await session.execute(select(ProxyUser).where(ProxyUser.name == name))
            ).scalar_one_or_none()
            if user is None:
                _fail("user not found", 1)
            user.enabled = enabled
            if enabled:
                user.disabled_reason = None
            await session.commit()
        await engine.dispose()

    _run(_set())
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
        async with factory() as session:
            user = (
                await session.execute(select(ProxyUser).where(ProxyUser.name == name))
            ).scalar_one_or_none()
            if user is None:
                _fail("user not found", 1)
            await rotate_credentials(session, store, user)
            token = await rotate_subscription(session, store, user) if subscription else None
            await session.commit()
        await engine.dispose()
        return token

    token = _run(_rotate())
    console.print(f"credentials rotated for {name}")
    if token:
        console.print(f"new subscription token: {token}")


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
        async with factory() as session:
            user = (
                await session.execute(select(ProxyUser).where(ProxyUser.name == name))
            ).scalar_one_or_none()
            if user is None:
                _fail("user not found", 1)
            await session.delete(user)
            await session.commit()
        await engine.dispose()

    _run(_remove())
    console.print(f"deleted {name}")


@user_app.command("quota")
def user_quota(
    name: str,
    quota: str = typer.Option(..., "--quota"),
    cycle: str = typer.Option("total", "--cycle"),
) -> None:
    """Set a user's quota."""

    from sqlalchemy import select

    from ostium.db.models import ProxyUser

    settings = _load_settings()

    async def _quota() -> None:
        engine, factory, _store = await _database(settings)
        async with factory() as session:
            user = (
                await session.execute(select(ProxyUser).where(ProxyUser.name == name))
            ).scalar_one_or_none()
            if user is None:
                _fail("user not found", 1)
            user.quota_bytes = _parse_bytes(quota)
            user.quota_cycle = cycle
            await session.commit()
        await engine.dispose()

    _run(_quota())
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
            await session.commit()
            data = {
                "token": token,
                "host": host,
                "formats": {
                    fmt: f"http://127.0.0.1:{settings.port}/sub/{token}?format={fmt}"
                    for fmt in ("ostium", "base64", "clash", "singbox")
                },
            }
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
        subscription_url = source
        response = httpx.get(source, timeout=20, follow_redirects=True, trust_env=False)
        response.raise_for_status()
        text = response.text
    else:
        path = Path(source)
        text = path.read_text(encoding="utf-8") if path.is_file() else source

    async def _import() -> int:
        engine, factory, store = await _database(settings)
        async with factory() as session:
            endpoints = parse_subscription_text(text)
            await create_profile(
                session,
                store,
                name=name,
                endpoints=endpoints,
                kind="subscription" if subscription_url else "manual",
                subscription_url=subscription_url,
            )
            await session.commit()
        await engine.dispose()
        return len(endpoints)

    count = _run(_import())
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
        engine, factory, _store = await _database(settings)
        async with factory() as session:
            profile = (
                await session.execute(select(Profile).where(Profile.name == name))
            ).scalar_one_or_none()
            if profile is None:
                _fail("profile not found", 1)
            await session.delete(profile)
            await session.commit()
        await engine.dispose()

    _run(_remove())
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
        async with factory() as session:
            profile = (
                await session.execute(select(Profile).where(Profile.name == name))
            ).scalar_one_or_none()
            if profile is None:
                _fail("profile not found", 1)
            count = await refresh_profile(session, store, profile)
            await session.commit()
        await engine.dispose()
        return count

    console.print(f"refreshed {_run(_refresh())} endpoint(s)")


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
    binary = settings.paths.engine_binary
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
    target = settings.paths.engine_binary
    target.parent.mkdir(parents=True, exist_ok=True)
    if manifest:
        try:
            if manifest.startswith(("http://", "https://")):
                response = httpx.get(manifest, timeout=30, follow_redirects=True, trust_env=False)
                response.raise_for_status()
                data = response.json()
            else:
                data = json.loads(Path(manifest).read_text(encoding="utf-8"))
        except Exception as exc:
            _fail(f"could not read core manifest: {exc}", 6)
        os_name = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}.get(
            platform.system(), platform.system().lower()
        )
        machine = platform.machine().lower()
        arch = "arm64" if machine in {"aarch64", "arm64"} else "amd64"
        candidates = [
            item
            for item in data.get("artifacts", [])
            if item.get("os") == os_name and item.get("arch") == arch
        ]
        if version:
            candidates = [item for item in candidates if item.get("version") == version]
        if not candidates:
            _fail(f"no core artifact for {os_name}/{arch} in the manifest", 6)
        artifact = sorted(candidates, key=lambda item: str(item.get("version")))[-1]
        response = httpx.get(
            str(artifact["url"]), timeout=180, follow_redirects=True, trust_env=False
        )
        response.raise_for_status()
        digest = hashlib.sha256(response.content).hexdigest()
        if digest != artifact["sha256"]:
            _fail("SHA256 mismatch; refusing to install", 6)
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
        response = httpx.get(url, timeout=120, follow_redirects=True, trust_env=False)
        response.raise_for_status()
        if sha256 and hashlib.sha256(response.content).hexdigest() != sha256:
            _fail("SHA256 mismatch; refusing to install", 6)
        target.write_bytes(response.content)
    else:
        _fail("provide --binary, --url or --manifest", 2)
    if os.name == "posix":
        target.chmod(0o755)
    console.print(f"installed core at {target}")


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
    result = create_backup(settings, password=password)
    console.print_json(json.dumps(result))


@backup_app.command("list")
def backup_list() -> None:
    """List backup files."""

    settings = _load_settings()
    for path in sorted(settings.paths.backups_dir.glob("ostium-backup-*")):
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
    os.system("systemctl daemon-reload")  # noqa: S605 - fixed command
    console.print("systemd units installed; enable with systemctl enable --now ostium-core ostium")


@service_app.command("uninstall")
def service_uninstall() -> None:
    """Remove systemd units (Linux, root)."""

    if sys.platform != "linux" or os.geteuid() != 0:
        _fail("run as root on Linux", 5)
    for name in ("ostium.service", "ostium-core.service"):
        Path("/etc/systemd/system", name).unlink(missing_ok=True)
    os.system("systemctl daemon-reload")  # noqa: S605 - fixed command
    console.print("systemd units removed (data is preserved)")


def _parse_bytes(value: str) -> int:
    value = value.strip().upper()
    units = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    if value[-1] in units:
        return int(float(value[:-1]) * units[value[-1]])
    return int(value)


if __name__ == "__main__":
    app()
