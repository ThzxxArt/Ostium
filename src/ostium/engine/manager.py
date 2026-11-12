"""Control-plane engine manager: database → sing-box config → core API."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ostium.config import Role, Settings
from ostium.db.models import Certificate, Inbound, Profile, ProxyUser, Rule, RuleSet
from ostium.engine.core_api import CoreApiError, CoreClient
from ostium.engine.singbox.config import (
    CertificateSpec,
    ClientConfigSpec,
    ClientTunSpec,
    RealitySpec,
    ServerConfigSpec,
    ServerInbound,
    UserCredential,
    build_client_config,
    build_server_config,
    config_digest,
)
from ostium.services.crypto import SecretStore
from ostium.services.events import EventBus
from ostium.services.stats import StatsCollector
from ostium.services.users import (
    decrypt_password,
    decrypt_ss_password,
    inbound_params,
)
from ostium.util.ids import new_token
from ostium.util.time import as_utc, utcnow


class EngineError(Exception):
    def __init__(self, message: str, code: str = "engine_error", status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class EngineManager:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        store: SecretStore,
        bus: EventBus,
        stats: StatsCollector | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.store = store
        self.bus = bus
        self.stats = stats
        self.client = CoreClient(settings)

    async def server_preview(self, session: AsyncSession) -> dict[str, Any]:
        spec = await self._server_spec(session)
        return build_server_config(spec)

    async def apply_server(self, session: AsyncSession) -> dict[str, Any]:
        config = await self.server_preview(session)
        digest = config_digest(config)
        try:
            result = await self.client.apply(config, digest, Role.SERVER.value)
        except CoreApiError as exc:
            raise EngineError(exc.detail, exc.code, exc.status_code) from exc
        await self._publish_applied("server", digest, result)
        return {"config": config, "status": result, "sha256": digest}

    async def client_preview(
        self,
        session: AsyncSession,
        *,
        mode: str | None = None,
        tun_enabled: bool | None = None,
        selected: str | None = None,
        routing_mode: str | None = None,
    ) -> dict[str, Any]:
        spec = await self._client_spec(
            session,
            mode=mode,
            tun_enabled=tun_enabled,
            selected=selected,
            routing_mode=routing_mode,
        )
        return build_client_config(spec)

    async def apply_client(
        self,
        session: AsyncSession,
        *,
        mode: str | None = None,
        tun_enabled: bool | None = None,
        selected: str | None = None,
        routing_mode: str | None = None,
    ) -> dict[str, Any]:
        config = await self.client_preview(
            session,
            mode=mode,
            tun_enabled=tun_enabled,
            selected=selected,
            routing_mode=routing_mode,
        )
        digest = config_digest(config)
        try:
            result = await self.client.apply(config, digest, Role.CLIENT.value)
        except CoreApiError as exc:
            raise EngineError(exc.detail, exc.code, exc.status_code) from exc
        await self._publish_applied("client", digest, result)
        return {"config": config, "status": result, "sha256": digest}

    async def _publish_applied(self, role: str, digest: str, result: dict[str, Any]) -> None:
        await self.bus.publish("engine.applied", {"role": role, "sha256": digest, "status": result})

    async def _server_spec(self, session: AsyncSession) -> ServerConfigSpec:
        users = (
            (await session.execute(select(ProxyUser).where(ProxyUser.enabled.is_(True))))
            .scalars()
            .all()
        )
        credentials = [
            UserCredential(
                name=user.name,
                uuid=user.uuid,
                password=decrypt_password(user, self.store),
                ss_password=decrypt_ss_password(user, self.store),
            )
            for user in users
        ]
        certs = (await session.execute(select(Certificate))).scalars().all()
        ready = [
            cert
            for cert in certs
            if cert.status == "ready" and cert.expires_at and as_utc(cert.expires_at) > utcnow()
        ]
        inbound_rows = (await session.execute(select(Inbound))).scalars().all()
        inbounds: list[ServerInbound] = []
        for inbound in inbound_rows:
            params = inbound_params(inbound, self.store)
            certificate = next(
                (cert for cert in ready if cert.id == inbound.certificate_id),
                ready[0] if ready else None,
            )
            reality = None
            if inbound.kind == "vless" and params.get("private_key"):
                reality = RealitySpec(
                    private_key=str(params["private_key"]),
                    short_id=str(params.get("short_id", "")),
                    server_name=str(params.get("server_name", "www.apple.com")),
                    handshake_server=params.get("handshake_server"),
                    handshake_port=int(params.get("handshake_port", 443)),
                )
            certificate_spec = (
                CertificateSpec(cert_path=certificate.cert_path, key_path=certificate.key_path)
                if certificate is not None
                else None
            )
            inbounds.append(
                ServerInbound(
                    kind=inbound.kind,
                    enabled=inbound.enabled,
                    listen=inbound.listen,
                    port=inbound.port,
                    reality=reality,
                    certificate=certificate_spec,
                    obfs_password=params.get("obfs_password"),
                    ss_server_key=params.get("server_key"),
                )
            )
        return ServerConfigSpec(
            inbounds=inbounds,
            users=credentials,
            clash_secret=self._clash_secret(),
            log_level=self.settings.log_level,
            enable_v2ray_api=True,
        )

    async def _client_spec(
        self,
        session: AsyncSession,
        *,
        mode: str | None = None,
        tun_enabled: bool | None = None,
        selected: str | None = None,
        routing_mode: str | None = None,
    ) -> ClientConfigSpec:
        from ostium.services.profiles import endpoints_from_profile

        profiles = (
            (
                await session.execute(
                    select(Profile).where(Profile.enabled.is_(True)).order_by(Profile.sort_order)
                )
            )
            .scalars()
            .all()
        )
        endpoints = []
        for profile in profiles:
            endpoints.extend(endpoints_from_profile(profile, self.store))
        if not endpoints:
            raise EngineError("no client profile is configured", "no_profile", 400)
        chosen = selected
        if chosen is None:
            active = next((profile for profile in profiles if profile.selected_endpoint), None)
            chosen = active.selected_endpoint if active else None
        rules = (
            (
                await session.execute(
                    select(Rule).where(Rule.enabled.is_(True)).order_by(Rule.priority)
                )
            )
            .scalars()
            .all()
        )
        rule_sets = (
            (await session.execute(select(RuleSet).where(RuleSet.enabled.is_(True))))
            .scalars()
            .all()
        )
        effective_mode = mode or self.settings.mode.value
        effective_tun = self.settings.tun_enabled if tun_enabled is None else tun_enabled
        from ostium.services.settings import get_setting

        stored_routing = await get_setting(session, "routing_mode", "smart")
        return ClientConfigSpec(
            endpoints=endpoints,
            mixed_port=self.settings.mixed_port,
            allow_lan=self.settings.allow_lan,
            mode=effective_mode,
            selected=chosen,
            routing_mode=routing_mode or str(stored_routing),
            rules=[dict(rule.match_json, action=rule.action) for rule in rules],
            rule_sets=[
                {
                    "tag": ruleset.name,
                    "url": ruleset.url,
                    "format": ruleset.format,
                    "path": ruleset.path,
                }
                for ruleset in rule_sets
            ],
            tun=ClientTunSpec(
                enabled=effective_tun,
                interface_name=self.settings.tun_interface,
            ),
            clash_secret=self._clash_secret(),
            log_level=self.settings.log_level,
            ipv6=True,
        )

    def _clash_secret(self) -> str:
        path = self.settings.paths.clash_secret_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            secret = path.read_text(encoding="utf-8").strip()
            if secret:
                return secret
        secret = new_token(24)
        path.write_text(secret, encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return secret


def server_host_from_config(config: dict[str, Any]) -> str | None:
    """Best-effort host extraction for diagnostics; never contains secrets."""
    inbounds = config.get("inbounds", [])
    if inbounds:
        return str(inbounds[0].get("listen", ""))
    return None
