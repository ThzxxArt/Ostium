from __future__ import annotations

import asyncio
import datetime as dt
import sqlite3
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from ostium.api import app as app_module
from ostium.api.app import _host_allowed, _origin_allowed, _run_housekeeping, build_app
from ostium.config import Role, Settings
from ostium.engine.manager import EngineError
from ostium.util.time import utcnow
from tests.conftest import csrf


def _settings(tmp_path: Path, role: Role = Role.SERVER, **overrides: object) -> Settings:
    value = Settings(
        role=role,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
        dev=True,
        log_level="warning",
        **overrides,
    )
    value.paths.ensure()
    value.save()
    return value


def _sql(settings: Settings, statement: str, params: tuple[object, ...] = ()) -> None:
    with sqlite3.connect(settings.paths.db_path) as connection:
        connection.execute(statement, params)
        connection.commit()


def test_host_and_origin_helpers() -> None:
    settings = Settings(
        data_dir=Path("/tmp/x"),
        config_dir=Path("/tmp/x"),
        state_dir=Path("/tmp/x"),
        core_token_file=Path("/tmp/x/token"),
        trusted_hosts=["example.com"],
    )
    assert _host_allowed("localhost:8443", settings) is True
    assert _host_allowed("[::1]:8443", settings) is True
    assert _host_allowed("127.0.0.1", settings) is True
    assert _host_allowed("192.168.1.1", settings) is True
    assert _host_allowed("example.com", settings) is True
    assert _host_allowed("sub.example.com", settings) is True
    assert _host_allowed("other.test", settings) is False
    assert _host_allowed("", settings) is False
    settings.trusted_hosts = []
    assert _host_allowed("other.test", settings) is False

    assert _origin_allowed("http://localhost:8443", "localhost:8443") is True
    assert _origin_allowed("https://example.com", "example.com") is True
    assert _origin_allowed("https://evil.example", "example.com") is False
    assert _origin_allowed("http://[", "example.com") is False
    assert _origin_allowed("urn:foo", "example.com") is False


def test_security_middleware_and_errors(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = build_app(settings)

    with TestClient(app, raise_server_exceptions=False) as client:
        invalid_host = client.get("/healthz", headers={"host": "evil.example"})
        assert invalid_host.status_code == 400
        assert invalid_host.json()["code"] == "invalid_host"

        bad_origin = client.get("/healthz", headers={"origin": "https://evil.example"})
        assert bad_origin.status_code == 403
        assert bad_origin.json()["code"] == "origin_rejected"

        good_origin = client.get(
            "/healthz", headers={"origin": "http://testserver", "host": "testserver"}
        )
        assert good_origin.status_code == 200
        assert good_origin.headers["X-Request-ID"]
        assert good_origin.headers["Content-Security-Policy"]
        assert good_origin.headers["Permissions-Policy"].startswith("camera=(self)")
        assert good_origin.cookies.get("ostium_csrf")

        too_large = client.post(
            "/api/v1/setup",
            content=b"{}",
            headers={"content-length": str(21 * 1024 * 1024)},
        )
        assert too_large.status_code == 413

        actual_large = client.post(
            "/api/v1/setup",
            content=b"x" * (20 * 1024 * 1024 + 1),
            headers={"content-type": "application/json"},
        )
        assert actual_large.status_code == 413

        csrf_failed = client.post("/api/v1/setup", json={})
        assert csrf_failed.status_code == 403
        assert csrf_failed.json()["code"] == "csrf_failed"

        token = csrf(client)
        mismatch = client.post("/api/v1/setup", json={}, headers={"X-CSRF-Token": token + "x"})
        assert mismatch.status_code == 403

        # Bearer-authenticated CLI requests bypass the cookie CSRF check.
        cli_token = (settings.paths.runtime_dir / "cli.token").read_text()
        bearer = client.post(
            "/api/v1/users",
            json={},
            headers={"Authorization": f"Bearer {cli_token}"},
        )
        # The request passed CSRF (Bearer requests are exempt) and reached
        # authentication, which fails because this app is not initialised.
        assert bearer.status_code == 401

        validation = client.post(
            "/api/v1/setup",
            json={"role": "server", "username": "", "password": "short"},
            headers={"X-CSRF-Token": token},
        )
        assert validation.status_code == 422
        assert validation.headers["content-type"].startswith("application/problem+json")


def test_unexpected_error_handler(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("ostium.config._locate_web_dist", lambda: None)
    app = build_app(_settings(tmp_path))

    @app.get("/api/v1/boom")
    async def boom() -> dict:
        raise RuntimeError("boom")

    @app.get("/api/v1/http-error")
    async def http_error() -> dict:
        from fastapi import HTTPException

        raise HTTPException(status_code=418, detail="teapot")

    with TestClient(app, raise_server_exceptions=False) as client:
        unhandled = client.get("/api/v1/boom")
        assert unhandled.status_code == 500
        assert unhandled.json()["code"] == "internal_error"

        handled = client.get("/api/v1/http-error")
        assert handled.status_code == 418
        assert handled.json()["code"] == "http_error"
        assert handled.json()["detail"] == "teapot"


def test_readyz_success_and_failure(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    app = build_app(settings)
    with TestClient(app) as client:
        services = app.state.services

        async def running() -> dict:
            return {"running": True}

        services.engine.client.status = running  # type: ignore[method-assign]
        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json() == {"ready": True, "checks": {"database": True, "core": True}}

        async def down() -> dict:
            raise RuntimeError("down")

        services.engine.client.status = down  # type: ignore[method-assign]
        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["checks"]["core"] is False

        class BrokenFactory:
            def __call__(self):
                raise RuntimeError("db down")

        services.session_factory = BrokenFactory()  # type: ignore[assignment]
        ready = client.get("/readyz")
        assert ready.status_code == 503
        assert ready.json()["ready"] is False


def test_spa_serving_and_traversal(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert settings.paths.web_dist is not None
    app = build_app(settings)
    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert "Ostium" in root.text
        assert client.get("/index.html").status_code == 200
        fallback = client.get("/dashboard")
        assert fallback.status_code == 200
        assert "Ostium" in fallback.text
        assert client.get("/api/v1/nope").status_code == 404
        traversal = client.get("/%2e%2e/%2e%2e/etc/passwd")
        assert traversal.status_code == 404


def test_spa_without_assets_or_index(tmp_path: Path, monkeypatch) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Ostium</title>")
    monkeypatch.setattr("ostium.config._locate_web_dist", lambda: dist)
    settings = _settings(tmp_path / "app")
    app = build_app(settings)
    with TestClient(app) as client:
        assert "Ostium" in client.get("/").text
        assert "Ostium" in client.get("/dashboard").text
        (dist / "index.html").unlink()
        unavailable = client.get("/dashboard")
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"] == "frontend is not built"


def test_no_frontend_branch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("ostium.config._locate_web_dist", lambda: None)
    settings = _settings(tmp_path)
    app = build_app(settings)
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Ostium API is running" in response.text


def test_client_auto_connect_branches(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, Role.CLIENT, auto_connect=True)
    calls: list[str] = []

    async def apply_client(self, session, **kwargs):  # type: ignore[no-untyped-def]
        calls.append("ok")
        return {"status": {"running": True}}

    monkeypatch.setattr(app_module.EngineManager, "apply_client", apply_client)
    app = build_app(settings)
    with TestClient(app):
        assert calls == ["ok"]
        assert any(
            "auto-connect applied" in item["message"] for item in app.state.services.bus.logs()
        )

    async def fail_client(self, session, **kwargs):  # type: ignore[no-untyped-def]
        raise EngineError("no profile", "no_profile", 400)

    monkeypatch.setattr(app_module.EngineManager, "apply_client", fail_client)
    settings2 = _settings(tmp_path / "second", Role.CLIENT, auto_connect=True)
    app2 = build_app(settings2)
    with TestClient(app2):
        assert any(
            "auto-connect skipped" in item["message"] for item in app2.state.services.bus.logs()
        )


def test_on_quota_callback(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    app = build_app(settings)
    with TestClient(app) as client:
        services = app.state.services
        assert services.stats is not None

        async def ok(self, session):  # type: ignore[no-untyped-def]
            return {"status": {"running": True}}

        monkeypatch.setattr(app_module.EngineManager, "apply_server", ok)
        client.portal.call(services.stats.on_quota, ["alice"])

        async def fail(self, session):  # type: ignore[no-untyped-def]
            raise RuntimeError("quota apply failed")

        monkeypatch.setattr(app_module.EngineManager, "apply_server", fail)
        client.portal.call(services.stats.on_quota, ["alice"])
        assert any(
            "quota configuration apply failed" in item["message"] for item in services.bus.logs()
        )


def test_housekeeping_cleans_expired_rows_and_alerts(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    app = build_app(settings)
    with TestClient(app) as client:
        services = app.state.services
        now = utcnow()
        old = (now - timedelta(days=2)).isoformat()
        _sql(
            settings,
            "INSERT INTO sessions "
            "(id,token_hash,admin_id,ip,user_agent,created_at,last_seen_at,expires_at,revoked) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("expired-session", "hash", "admin", None, None, old, old, old, 0),
        )
        for job_id, status in (
            ("old-done", "succeeded"),
            ("old-running", "running"),
        ):
            _sql(
                settings,
                "INSERT INTO jobs (id,type,status,progress,message,created_at,cancel_requested) "
                "VALUES (?,?,?,?,?,?,?)",
                (job_id, "test", status, 0, "", old, 0),
            )
        for index, days in enumerate((30, 5, -1)):
            _sql(
                settings,
                "INSERT INTO certificates "
                "(id,domain,cert_path,key_path,issuer,expires_at,auto_renew,status,"
                "source,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"hk-{index}",
                    f"hk{index}.example.com",
                    "/tmp/c",
                    "/tmp/k",
                    "issuer",
                    (now + timedelta(days=days)).isoformat(),
                    1,
                    "ready",
                    "manual",
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        _sql(
            settings,
            "INSERT INTO certificates "
            "(id,domain,cert_path,key_path,issuer,expires_at,auto_renew,status,"
            "source,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "no-expiry",
                "no-expiry.example.com",
                "/tmp/c",
                "/tmp/k",
                "issuer",
                None,
                1,
                "ready",
                "manual",
                now.isoformat(),
                now.isoformat(),
            ),
        )

        monkeypatch.setattr(
            "psutil.disk_usage",
            lambda path: SimpleNamespace(percent=95.0),
        )
        client.portal.call(_run_housekeeping, services)
        with sqlite3.connect(settings.paths.db_path) as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM sessions WHERE id='expired-session'"
                ).fetchone()[0]
                == 0
            )
            jobs = dict(connection.execute("SELECT id,status FROM jobs").fetchall())
            assert "old-done" not in jobs
            assert jobs["old-running"] == "running"
            alerts = [row[0] for row in connection.execute("SELECT message FROM alerts").fetchall()]
        assert any("hk1.example.com" in message and "expires in" in message for message in alerts)
        assert any("hk2.example.com" in message and "expires in" in message for message in alerts)
        assert any("data disk is 95% full" in message for message in alerts)


def test_housekeeping_loop_logs_failure(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    app = build_app(settings)
    with TestClient(app) as client:
        services = app.state.services

        async def fail(services):  # type: ignore[no-untyped-def]
            raise RuntimeError("housekeeping exploded")

        monkeypatch.setattr(app_module, "_run_housekeeping", fail)
        real_sleep = asyncio.sleep
        calls = {"count": 0}

        async def sleep(seconds):  # type: ignore[no-untyped-def]
            calls["count"] += 1
            if calls["count"] == 1:
                await real_sleep(0)
                return
            raise asyncio.CancelledError

        monkeypatch.setattr(app_module.asyncio, "sleep", sleep)
        client.portal.call(app_module._housekeeping, services)
        assert any("housekeeping failed" in item["message"] for item in services.bus.logs())


def _bundle(domain: str) -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=90))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(domain)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return (
        certificate.public_bytes(serialization.Encoding.PEM).decode(),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )


def test_cert_renewal_loop(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    app = build_app(settings)
    with TestClient(app) as client:
        services = app.state.services
        bundle = _bundle("renew.example.com")
        now = utcnow()
        for cert_id, domain, days, source, auto in (
            ("renew-me", "renew.example.com", 10, "acme", 1),
            ("fresh", "fresh.example.com", 60, "acme", 1),
            ("manual", "manual.example.com", 10, "manual", 1),
            ("no-auto", "noauto.example.com", 10, "acme", 0),
        ):
            _sql(
                settings,
                "INSERT INTO certificates "
                "(id,domain,cert_path,key_path,issuer,expires_at,auto_renew,status,"
                "source,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    cert_id,
                    domain,
                    "/tmp/c",
                    "/tmp/k",
                    "issuer",
                    (now + timedelta(days=days)).isoformat(),
                    auto,
                    "ready",
                    source,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )

        renewed: list[str] = []

        class Issuer:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def issue(self, domain: str) -> tuple[str, str]:
                renewed.append(domain)
                return bundle

        monkeypatch.setattr("ostium.acme.client.AcmeIssuer", Issuer)

        async def ok(self, session):  # type: ignore[no-untyped-def]
            return {"status": {"running": True}}

        monkeypatch.setattr(app_module.EngineManager, "apply_server", ok)
        real_sleep = asyncio.sleep
        calls = {"count": 0}

        async def sleep(seconds):  # type: ignore[no-untyped-def]
            calls["count"] += 1
            if calls["count"] == 1:
                await real_sleep(0)
                return
            raise asyncio.CancelledError

        monkeypatch.setattr(app_module.asyncio, "sleep", sleep)
        client.portal.call(app_module._cert_renewal, services)
        assert renewed == ["renew.example.com"]
        assert any("certificate renewed" in item["message"] for item in services.bus.logs())


def test_profile_refresh_loop(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path, Role.CLIENT)
    app = build_app(settings)
    with TestClient(app) as client:
        services = app.state.services
        from ostium.services.crypto import SecretStore

        store = SecretStore.from_data_dir(settings.data_dir)
        now = utcnow()
        for profile_id, name, url in (
            ("good", "good", "https://sub.example.com/good"),
            ("bad", "bad", "https://sub.example.com/bad"),
        ):
            enc = store.encrypt(
                url, table="profiles", record_id=profile_id, field="subscription_url"
            )
            config = store.encrypt("{}", table="profiles", record_id=profile_id, field="config")
            _sql(
                settings,
                "INSERT INTO profiles "
                "(id,name,kind,config_enc,subscription_url_enc,enabled,sort_order,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    profile_id,
                    name,
                    "subscription",
                    config,
                    enc,
                    1,
                    0,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )

        async def refresh(session, store, profile):  # type: ignore[no-untyped-def]
            if profile.name == "bad":
                raise RuntimeError("refresh failed")
            return 1

        monkeypatch.setattr(app_module, "refresh_profile", refresh, raising=False)
        monkeypatch.setattr("ostium.services.profiles.refresh_profile", refresh)
        real_sleep = asyncio.sleep
        calls = {"count": 0}

        async def sleep(seconds):  # type: ignore[no-untyped-def]
            calls["count"] += 1
            if calls["count"] == 1:
                await real_sleep(0)
                return
            raise asyncio.CancelledError

        monkeypatch.setattr(app_module.asyncio, "sleep", sleep)
        client.portal.call(app_module._profile_refresh, services)
        logs = [item["message"] for item in services.bus.logs()]
        assert "subscription refreshed" in logs
        assert any("subscription refresh failed" in item for item in logs)


def test_cert_renewal_and_profile_refresh_outer_errors(tmp_path: Path, monkeypatch) -> None:
    server_settings = _settings(tmp_path / "server")
    server_app = build_app(server_settings)
    with TestClient(server_app) as client:
        services = server_app.state.services
        calls = {"count": 0}

        async def failing_sleep(seconds):  # type: ignore[no-untyped-def]
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("sleep exploded")
            raise asyncio.CancelledError

        monkeypatch.setattr(app_module.asyncio, "sleep", failing_sleep)
        # The first iteration raises inside the try before the certificate
        # query; the loop catches, logs, then exits on CancelledError.
        client.portal.call(app_module._cert_renewal, services)
        assert any(
            "certificate renewal loop failed" in item["message"] for item in services.bus.logs()
        )

    client_settings = _settings(tmp_path / "client", Role.CLIENT)
    client_app = build_app(client_settings)
    with TestClient(client_app) as client:
        services = client_app.state.services
        calls = {"count": 0}

        async def failing_sleep(seconds):  # type: ignore[no-untyped-def]
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("sleep exploded")
            raise asyncio.CancelledError

        monkeypatch.setattr(app_module.asyncio, "sleep", failing_sleep)
        client.portal.call(app_module._profile_refresh, services)
        assert any("profile refresh loop failed" in item["message"] for item in services.bus.logs())
