"""Certificate renewal must signal the TLS listener (P0-04)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from ostium.api.app import _cert_renewal
from ostium.config import Role, Settings
from ostium.db.models import Certificate
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.services.crypto import SecretStore
from ostium.services.events import EventBus
from ostium.util.time import utcnow


def test_certificate_renewal_writes_the_tls_reload_marker(tmp_path: Path, monkeypatch) -> None:
    async def _run() -> None:
        settings = Settings(
            role=Role.SERVER,
            data_dir=tmp_path / "data",
            config_dir=tmp_path / "config",
            state_dir=tmp_path / "state",
            core_token_file=tmp_path / "data" / "runtime" / "core.token",
            dev=True,
        )
        settings.paths.ensure()
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        cert_path = settings.paths.certs_dir / "vpn.example.com" / "fullchain-old.pem"
        key_path = settings.paths.certs_dir / "vpn.example.com" / "privkey-old.pem"
        cert_path.parent.mkdir(parents=True, exist_ok=True)
        cert_path.write_text("old-cert", encoding="utf-8")
        key_path.write_text("old-key", encoding="utf-8")
        async with factory() as session:
            session.add(
                Certificate(
                    domain="vpn.example.com",
                    cert_path=str(cert_path),
                    key_path=str(key_path),
                    expires_at=utcnow() + timedelta(days=10),
                    status="ready",
                    source="acme",
                    auto_renew=True,
                )
            )
            await session.commit()

        async def issue(self, domain):  # type: ignore[no-untyped-def]
            return "new-cert", "new-key"

        async def import_manual(session, settings_arg, **kwargs):  # type: ignore[no-untyped-def]
            return None

        class Engine:
            async def apply_server(self, session):  # type: ignore[no-untyped-def]
                return {"status": {"running": True}}

        monkeypatch.setattr("ostium.acme.client.AcmeIssuer.issue", issue)
        monkeypatch.setattr("ostium.services.certificates.import_manual", import_manual)
        services = SimpleNamespace(
            session_factory=factory,
            settings=settings,
            store=store,
            bus=EventBus(),
            engine=Engine(),
        )

        async def stop_after_work(seconds):  # type: ignore[no-untyped-def]
            raise asyncio.CancelledError

        await _cert_renewal(services, stop_after_work)
        marker = settings.paths.runtime_dir / "reload-ui"
        assert marker.is_file()
        await engine.dispose()

    asyncio.run(_run())


def _headers(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


def test_public_ui_certificate_cannot_be_deleted(
    api_client: TestClient, session_token: str
) -> None:
    issued = api_client.post(
        "/api/v1/certificates/issue",
        json={"domain": "vpn.example.com", "method": "self-signed"},
        headers=_headers(session_token),
    )
    assert issued.status_code == 202, issued.text
    certificate_id = issued.json()["certificate"]["id"]
    services = api_client.app.state.services
    services.settings.public_ui = True

    async def _bind() -> None:
        from ostium.services.settings import set_setting

        async with services.session_factory() as session:
            await set_setting(session, "server", {"domain": "vpn.example.com"})
            await session.commit()

    asyncio.run(_bind())
    deleted = api_client.delete(
        f"/api/v1/certificates/{certificate_id}", headers=_headers(session_token)
    )
    assert deleted.status_code == 409
    assert deleted.json()["code"] == "certificate_in_use"
