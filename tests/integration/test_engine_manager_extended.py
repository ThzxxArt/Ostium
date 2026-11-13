from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from ostium.config import Mode, Role, Settings
from ostium.db.models import Inbound, Rule, RuleSet
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.domain.endpoints import Endpoint, Protocol, TLSConfig
from ostium.engine.core_api import CoreApiError
from ostium.engine.manager import EngineError, EngineManager, server_host_from_config
from ostium.services.certificates import create_self_signed
from ostium.services.crypto import SecretStore
from ostium.services.events import EventBus
from ostium.services.profiles import create_profile
from ostium.services.settings import set_setting
from ostium.services.users import create_user, ensure_inbounds
from ostium.util.time import utcnow


def _settings(tmp_path: Path, role: Role = Role.SERVER) -> Settings:
    value = Settings(
        role=role,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
        engine_path=str(tmp_path / "sing-box"),
        proxy_ports=[443, 8388],
        dev=True,
    )
    value.paths.ensure()
    return value


async def _setup(settings: Settings):
    engine = create_engine(settings.paths.db_path)
    await create_schema(engine)
    factory = create_session_factory(engine)
    store = SecretStore.from_data_dir(settings.data_dir)
    manager = EngineManager(settings, factory, store, EventBus())
    return engine, factory, store, manager


def test_server_spec_certificates_and_protocols(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine, factory, store, manager = await _setup(settings)
        async with factory() as session:
            await ensure_inbounds(session, store)
            await create_user(session, store, name="alice")
            cert = await create_self_signed(session, settings, domain="vpn.example.com")
            await session.commit()
            inbounds = {row.kind: row for row in (await session.execute(select(Inbound))).scalars()}
            for inbound in inbounds.values():
                inbound.enabled = True
            inbounds["vless"].params_enc = store.encrypt(
                '{"private_key":"pk","short_id":"sid","server_name":"sni","handshake_server":"hs","handshake_port":8443}',
                table="inbounds",
                record_id=inbounds["vless"].id,
                field="params",
            )
            inbounds["hysteria2"].certificate_id = cert.id
            inbounds["hysteria2"].params_enc = store.encrypt(
                '{"obfs_password":"obfs"}',
                table="inbounds",
                record_id=inbounds["hysteria2"].id,
                field="params",
            )
            inbounds["shadowsocks"].params_enc = store.encrypt(
                '{"server_key":"ss-key"}',
                table="inbounds",
                record_id=inbounds["shadowsocks"].id,
                field="params",
            )
            await session.commit()

            preview = await manager.server_preview(session)
            by_type = {item["type"]: item for item in preview["inbounds"]}
            assert by_type["vless"]["tls"]["reality"]["handshake"]["server"] == "hs"
            assert by_type["hysteria2"]["obfs"]["password"] == "obfs"
            assert by_type["hysteria2"]["tls"]["certificate_path"] == cert.cert_path
            assert by_type["shadowsocks"]["password"] == "ss-key"

            # Expired certificates are not eligible; the inbound then has no TLS.
            cert.expires_at = utcnow() - timedelta(days=1)
            await session.flush()
            preview = await manager.server_preview(session)
            by_type = {item["type"]: item for item in preview["inbounds"]}
            assert "hysteria2" not in by_type
            assert "trojan" not in by_type

            # Certificates are bound per inbound; there is no global fallback.
            cert.expires_at = utcnow() + timedelta(days=30)
            cert.status = "ready"
            inbounds["trojan"].certificate_id = cert.id
            await session.flush()
            preview = await manager.server_preview(session)
            trojan = next(item for item in preview["inbounds"] if item["type"] == "trojan")
            assert trojan["tls"]["certificate_path"] == cert.cert_path

            inbounds["trojan"].certificate_id = None
            await session.flush()
            preview = await manager.server_preview(session)
            assert all(item["type"] != "trojan" for item in preview["inbounds"])

            async def ok(config, digest, role):  # type: ignore[no-untyped-def]
                return {"running": True, "revision": digest[:16], "role": role}

            async def fail(config, digest, role):  # type: ignore[no-untyped-def]
                raise CoreApiError(503, "core down", "core_unreachable")

            manager.client.apply = ok  # type: ignore[method-assign]
            applied = await manager.apply_server(session)
            assert applied["status"]["running"] is True
            assert applied["sha256"]

            manager.client.apply = fail  # type: ignore[method-assign]
            with pytest.raises(EngineError) as excinfo:
                await manager.apply_server(session)
            assert excinfo.value.code == "core_unreachable"
        await engine.dispose()

    asyncio.run(_run())


def test_client_spec_selection_rules_and_errors(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path, Role.CLIENT)
        engine, factory, store, manager = await _setup(settings)
        async with factory() as session:
            with pytest.raises(EngineError) as missing:
                await manager.client_preview(session)
            assert missing.value.code == "no_profile"

            endpoint = Endpoint(
                tag="hk",
                protocol=Protocol.VLESS_REALITY,
                name="HK",
                server="vpn.example.com",
                port=443,
                uuid="uuid",
                tls=TLSConfig(server_name="sni", reality_public_key="pub", reality_short_id="sid"),
            )
            first = await create_profile(session, store, name="first", endpoints=[endpoint])
            second = await create_profile(session, store, name="second", endpoints=[endpoint])
            first.selected_endpoint = "hk"
            second.selected_endpoint = "other"
            session.add(
                Rule(
                    action="direct",
                    match_json={"domain_suffix": [".cn"]},
                    priority=10,
                )
            )
            session.add(
                RuleSet(
                    name="ads", url="https://example.com/ads.srs", format="binary", enabled=True
                )
            )
            session.add(
                RuleSet(
                    name="off",
                    url="https://example.com/off.srs",
                    format="source",
                    enabled=False,
                )
            )
            await set_setting(session, "routing_mode", "global")
            await session.commit()

            config = await manager.client_preview(session)
            assert config["route"]["final"] == "proxy"
            selector = next(item for item in config["outbounds"] if item["type"] == "selector")
            assert selector["default"] == "first-hk"
            assert any(rule.get("outbound") == "direct" for rule in config["route"]["rules"])
            assert [item["tag"] for item in config["route"]["rule_set"]] == ["ads"]

            explicit = await manager.client_preview(
                session, selected="second-hk", routing_mode="direct"
            )
            selector = next(item for item in explicit["outbounds"] if item["type"] == "selector")
            assert selector["default"] == "second-hk"
            assert explicit["route"]["final"] == "direct"

            settings.mode = Mode.TUN
            settings.tun_enabled = True
            config = await manager.client_preview(session)
            assert any(item["type"] == "tun" for item in config["inbounds"])

            async def ok(config, digest, role):  # type: ignore[no-untyped-def]
                return {"running": True, "revision": digest[:16], "role": role}

            async def fail(config, digest, role):  # type: ignore[no-untyped-def]
                raise CoreApiError(422, "bad config", "engine_check_failed")

            manager.client.apply = ok  # type: ignore[method-assign]
            applied = await manager.apply_client(session, mode="mixed", tun_enabled=False)
            assert applied["status"]["running"] is True

            manager.client.apply = fail  # type: ignore[method-assign]
            with pytest.raises(EngineError) as excinfo:
                await manager.apply_client(session)
            assert excinfo.value.code == "engine_check_failed"
        await engine.dispose()

    asyncio.run(_run())


def test_clash_secret_reuse_and_host_extraction(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    manager = EngineManager(
        settings,
        create_session_factory(create_engine(settings.paths.db_path)),
        SecretStore.from_data_dir(settings.data_dir),
        EventBus(),
    )
    first = manager._clash_secret()
    assert settings.paths.clash_secret_path.read_text().strip() == first
    assert manager._clash_secret() == first

    settings.paths.clash_secret_path.write_text("   ")
    second = manager._clash_secret()
    assert second != first

    assert server_host_from_config({"inbounds": [{"listen": "0.0.0.0"}]}) == "0.0.0.0"
    assert server_host_from_config({}) is None
