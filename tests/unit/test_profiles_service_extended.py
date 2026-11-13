from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest
import respx

from ostium.config import Role, Settings
from ostium.db.session import create_engine, create_schema, create_session_factory
from ostium.domain.endpoints import Endpoint
from ostium.services.crypto import SecretStore
from ostium.services.profiles import (
    ProfileError,
    _from_clash,
    _from_singbox_outbounds,
    _maybe_base64,
    _tag,
    create_profile,
    endpoints_from_profile,
    get_active_profiles,
    parse_subscription_text,
    refresh_profile,
    serialize_profile,
    subscription_url_of,
)

VLESS = (
    "vless://2d4f2f26-6f4f-4f17-9a1f-1a5d63500f0e@vpn.example.com:443"
    "?encryption=none&security=reality&sni=www.apple.com&fp=chrome"
    "&pbk=pub&sid=55e1651e&type=tcp&flow=xtls-rprx-vision#HK"
)


def _settings(tmp_path: Path) -> Settings:
    value = Settings(
        role=Role.CLIENT,
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        state_dir=tmp_path / "state",
        core_token_file=tmp_path / "data" / "runtime" / "core.token",
        dev=True,
    )
    value.paths.ensure()
    return value


def test_parse_errors() -> None:
    with pytest.raises(ProfileError, match="invalid JSON"):
        parse_subscription_text('{"endpoints":')
    with pytest.raises(ProfileError, match="does not contain"):
        parse_subscription_text('{"something": true}')
    with pytest.raises(ProfileError, match="unsupported entries"):
        parse_subscription_text("vmess://abc")
    assert parse_subscription_text("\n# comment\n" + VLESS).__len__() == 1


def test_maybe_base64_variants() -> None:
    assert _maybe_base64(VLESS) is None
    encoded = base64.b64encode(VLESS.encode()).decode()
    spaced = " ".join(encoded[i : i + 8] for i in range(0, len(encoded), 8))
    assert _maybe_base64(spaced) is not None
    assert _maybe_base64("!!!not-base64!!!") is None
    assert _maybe_base64("not a subscription") is None


def test_clash_all_types_and_errors() -> None:
    document = """
proxies:
  - name: reality
    type: vless
    server: vpn.example.com
    port: 443
    uuid: uuid
    flow: ""
    servername: sni
    reality-opts:
      public-key: pub
      short-id: sid
  - name: hy
    type: hysteria2
    server: hy.example.com
    port: 8443
    password: pass
    sni: sni
    skip-cert-verify: true
  - name: tj
    type: trojan
    server: tj.example.com
    port: 443
    password: pass
    servername: sni
  - name: ss
    type: ss
    server: ss.example.com
    port: 8388
    cipher: aes-128-gcm
    password: pass
  - name: unknown
    type: vmess
    server: x
    port: 1
  - name: missing
    type: vless
  - just-a-string
"""
    endpoints = _from_clash(document)
    assert [item.protocol.value for item in endpoints] == [
        "vless-reality",
        "hysteria2",
        "trojan",
        "shadowsocks",
    ]
    assert endpoints[0].flow == "xtls-rprx-vision"
    assert endpoints[1].tls.insecure is True
    assert endpoints[3].method == "aes-128-gcm"

    with pytest.raises(ProfileError, match="invalid Clash YAML"):
        _from_clash("proxies: [")
    with pytest.raises(ProfileError, match="no supported proxy"):
        _from_clash("proxies: []")
    with pytest.raises(ProfileError, match="no supported proxy"):
        _from_clash("- not-a-dict")


def test_singbox_all_types_and_errors() -> None:
    outbounds = [
        {
            "type": "vless",
            "tag": "reality",
            "server": "vpn.example.com",
            "server_port": 443,
            "uuid": "uuid",
            "flow": "",
            "tls": {
                "server_name": "sni",
                "reality": {"public_key": "pub", "short_id": "sid"},
                "utls": {"fingerprint": "firefox"},
            },
        },
        {
            "type": "hysteria2",
            "server": "hy.example.com",
            "server_port": 8443,
            "password": "pass",
            "tls": {"server_name": "sni", "insecure": True},
        },
        {
            "type": "trojan",
            "tag": "tj",
            "server": "tj.example.com",
            "server_port": 443,
            "password": "pass",
            "tls": {"server_name": "sni"},
        },
        {
            "type": "shadowsocks",
            "tag": "ss",
            "server": "ss.example.com",
            "server_port": 8388,
            "method": "aes-128-gcm",
            "password": "pass",
        },
        {"type": "wireguard", "server": "x", "server_port": 1},
        {"type": "vless", "server": "missing-port"},
        "not-a-dict",
    ]
    endpoints = _from_singbox_outbounds(outbounds)
    assert [item.protocol.value for item in endpoints] == [
        "vless-reality",
        "hysteria2",
        "trojan",
        "shadowsocks",
    ]
    assert endpoints[0].tls.fingerprint == "firefox"
    assert endpoints[1].tls.insecure is True
    with pytest.raises(ProfileError, match="no supported outbound"):
        _from_singbox_outbounds([{"type": "wireguard"}])


def test_tags() -> None:
    assert _tag("Hello World", 2) == "hello-world-2"
    assert _tag("!!!", 0) == "endpoint-0"
    assert len(_tag("a" * 100, 1)) <= 52


def test_profile_storage_and_serialization(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        async with factory() as session:
            endpoint = Endpoint.from_uri(VLESS)
            profile = await create_profile(
                session,
                store,
                name="HK",
                endpoints=[endpoint],
                kind="subscription",
                subscription_url="https://example.com/sub",
            )
            await session.commit()
            assert subscription_url_of(profile, store) == "https://example.com/sub"
            assert endpoints_from_profile(profile, store)[0].tag == endpoint.tag
            data = serialize_profile(profile, store)
            assert data["endpoints"][0]["protocol"] == "vless-reality"
            assert data["subscription_url"] == "https://example.com/sub"

            profile.config_enc = "v1.invalid"
            assert serialize_profile(profile, store)["endpoints"] == []
            with pytest.raises(ProfileError, match="corrupted"):
                endpoints_from_profile(profile, store)

            manual = await create_profile(session, store, name="manual", endpoints=[endpoint])
            await session.commit()
            assert subscription_url_of(manual, store) is None
        await engine.dispose()

    asyncio.run(_run())


def test_refresh_profile(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        async with factory() as session:
            profile = await create_profile(
                session,
                store,
                name="HK",
                endpoints=[Endpoint.from_uri(VLESS)],
                kind="subscription",
                subscription_url="https://example.com/sub",
            )
            await session.commit()
            with respx.mock:
                route = respx.get("https://example.com/sub").mock(
                    return_value=httpx.Response(200, text=VLESS)
                )
                count = await refresh_profile(session, store, profile)
                await session.commit()
                assert count == 1
                assert route.called

            with respx.mock:
                respx.get("https://example.com/sub").mock(
                    return_value=httpx.Response(500, text="nope")
                )
                with pytest.raises(ProfileError) as excinfo:
                    await refresh_profile(session, store, profile)
                assert excinfo.value.code == "refresh_failed"
                assert profile.last_refresh_error

            with respx.mock:
                respx.get("https://example.com/sub").mock(
                    return_value=httpx.Response(200, text="not a subscription")
                )
                with pytest.raises(ProfileError):
                    await refresh_profile(session, store, profile)

            profile.subscription_url_enc = None
            with pytest.raises(ProfileError, match="no subscription URL"):
                await refresh_profile(session, store, profile)
        await engine.dispose()

    asyncio.run(_run())


def test_active_profiles_order(tmp_path: Path) -> None:
    async def _run() -> None:
        settings = _settings(tmp_path)
        engine = create_engine(settings.paths.db_path)
        await create_schema(engine)
        factory = create_session_factory(engine)
        store = SecretStore.from_data_dir(settings.data_dir)
        async with factory() as session:
            first = await create_profile(
                session, store, name="b", endpoints=[Endpoint.from_uri(VLESS)]
            )
            second = await create_profile(
                session, store, name="a", endpoints=[Endpoint.from_uri(VLESS)]
            )
            first.sort_order = 20
            second.sort_order = 10
            disabled = await create_profile(
                session, store, name="c", endpoints=[Endpoint.from_uri(VLESS)]
            )
            disabled.enabled = False
            await session.commit()
            rows = await get_active_profiles(session)
            assert [row.name for row in rows] == ["a", "b"]
        await engine.dispose()

    asyncio.run(_run())


def test_profile_document_invalid_shape() -> None:
    with pytest.raises(ProfileError, match="invalid Ostium profile"):
        parse_subscription_text(json.dumps({"endpoints": "not-a-list"}))
    with pytest.raises(ProfileError, match="no supported outbound"):
        parse_subscription_text(json.dumps({"outbounds": [{"type": "vless", "server": "x"}]}))
    with pytest.raises(ProfileError, match="invalid Clash"):
        parse_subscription_text(
            "proxies:\n  - name: bad\n    type: vless\n    server: x\n    port: not-a-port\n"
        )
