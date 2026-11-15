"""Control-plane engine manager: database → sing-box config → core API."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
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
    namespace_endpoint_tags,
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
from ostium.util.paths import resolve_path
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
        # Every apply reaches the same privileged core.  Serialising them here
        # prevents two requests that read different database snapshots from
        # overwriting each other out of order.
        self._apply_lock = asyncio.Lock()
        self._last_applied: dict[str, str] = {}

    async def server_preview(self, session: AsyncSession) -> dict[str, Any]:
        spec = await self._server_spec(session)
        return build_server_config(spec)

    async def apply_server(self, session: AsyncSession) -> dict[str, Any]:
        async with self._apply_lock:
            config = await self.server_preview(session)
            digest = config_digest(config)
            try:
                result = await self.client.apply(config, digest, Role.SERVER.value)
            except CoreApiError as exc:
                raise EngineError(exc.detail, exc.code, exc.status_code) from exc
            self._last_applied["server"] = digest
            await self._publish_applied("server", digest, result)
            return {"config": config, "status": result, "sha256": digest}

    async def reconcile_server(self, session: AsyncSession, *, force: bool = False) -> bool:
        """Apply the database configuration when the running core is stale.

        Returns ``True`` when an apply was attempted.  This is the safety net
        for an apply that failed after the database commit, and for an upgrade
        that left an old ``last-good.json`` behind: the next tick converges the
        core to the database instead of waiting for an unrelated admin action.
        """

        config = await self.server_preview(session)
        digest = config_digest(config)
        if not force and self._last_applied.get("server") == digest:
            return False
        await self.apply_server(session)
        return True

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
        async with self._apply_lock:
            config = await self.client_preview(
                session,
                mode=mode,
                tun_enabled=tun_enabled,
                selected=selected,
                routing_mode=routing_mode,
            )
            artifacts = self._client_artifacts(config)
            digest = config_digest(config)
            try:
                result = await self.client.apply(
                    config, digest, Role.CLIENT.value, artifacts=artifacts
                )
            except CoreApiError as exc:
                raise EngineError(exc.detail, exc.code, exc.status_code) from exc
            self._last_applied["client"] = digest
            await self._publish_applied("client", digest, result)
            return {"config": config, "status": result, "sha256": digest}

    def _client_artifacts(self, config: dict[str, Any]) -> dict[str, str]:
        """Upload rule-set bytes that the privileged core cannot read.

        On a default client install the UI runs as the desktop user while the
        core runs as ``ostium-core`` with its own private data directory.  The
        generated config references rule-set files in the UI data directory;
        without transferring the bytes the core rejects those paths.
        """

        artifacts: dict[str, str] = {}
        route = config.get("route")
        if not isinstance(route, dict):
            return artifacts
        entries = route.get("rule_set")
        if not isinstance(entries, list):
            return artifacts
        total = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw = entry.get("path")
            if not isinstance(raw, str) or not raw:
                continue
            try:
                data = Path(raw).read_bytes()
            except OSError as exc:
                raise EngineError(
                    f"rule set file is not readable: {raw}", "rule_set_unreadable", 400
                ) from exc
            total += len(data)
            if len(data) > 16 * 1024 * 1024 or total > 32 * 1024 * 1024:
                raise EngineError("rule set file is too large", "rule_set_too_large", 413)
            artifacts[raw] = base64.b64encode(data).decode("ascii")
        return artifacts

    async def reconcile_client(self, session: AsyncSession, *, force: bool = False) -> bool:
        config = await self.client_preview(session)
        digest = config_digest(config)
        if not force and self._last_applied.get("client") == digest:
            return False
        await self.apply_client(session)
        return True

    async def _publish_applied(self, role: str, digest: str, result: dict[str, Any]) -> None:
        await self.bus.publish("engine.applied", {"role": role, "sha256": digest, "status": result})

    async def _server_spec(self, session: AsyncSession) -> ServerConfigSpec:
        users = (
            (await session.execute(select(ProxyUser).where(ProxyUser.enabled.is_(True))))
            .scalars()
            .all()
        )
        now = utcnow()
        active: list[ProxyUser] = []
        for user in users:
            # Enforcement must not depend on the statistics loop: a user whose
            # expiry or quota has already passed is never written into a new
            # configuration, even before the next quota tick disables the row.
            if user.expires_at is not None and as_utc(user.expires_at) <= now:
                continue
            if user.quota_bytes > 0:
                pending = self.stats.pending_bytes(user.id) if self.stats is not None else 0
                if user.used_bytes + pending >= user.quota_bytes:
                    continue
            active.append(user)
        credentials = [
            UserCredential(
                name=user.name,
                uuid=user.uuid,
                password=decrypt_password(user, self.store),
                ss_password=decrypt_ss_password(user, self.store),
            )
            for user in active
        ]
        certs = (await session.execute(select(Certificate))).scalars().all()
        ready: dict[str, Certificate] = {}
        for cert in certs:
            cert_file = resolve_path(self.settings, cert.cert_path)
            key_file = resolve_path(self.settings, cert.key_path)
            if (
                cert.status == "ready"
                and cert.expires_at is not None
                and as_utc(cert.expires_at) > utcnow()
                and cert_file is not None
                and key_file is not None
                and cert_file.is_file()
                and key_file.is_file()
            ):
                ready[cert.id] = cert
        inbound_rows = (await session.execute(select(Inbound))).scalars().all()
        inbounds: list[ServerInbound] = []
        for inbound in inbound_rows:
            params = inbound_params(inbound, self.store)
            # Certificates are bound per inbound.  Never fall back to an
            # arbitrary ready certificate: that silently serves a mismatched
            # domain and breaks client verification.
            certificate = ready.get(inbound.certificate_id or "")
            reality = None
            if inbound.kind == "vless" and params.get("private_key"):
                reality = RealitySpec(
                    private_key=str(params["private_key"]),
                    short_id=str(params.get("short_id", "")),
                    server_name=str(params.get("server_name", "www.apple.com")),
                    handshake_server=params.get("handshake_server"),
                    handshake_port=int(params.get("handshake_port", 443)),
                )
            certificate_spec = None
            if certificate is not None:
                cert_file = resolve_path(self.settings, certificate.cert_path)
                key_file = resolve_path(self.settings, certificate.key_path)
                if cert_file is not None and key_file is not None:
                    certificate_spec = CertificateSpec(
                        cert_path=str(cert_file), key_path=str(key_file)
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
            block_private_egress=self.settings.block_private_egress,
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
        from ostium.services.settings import get_setting

        profiles = (
            (
                await session.execute(
                    select(Profile).where(Profile.enabled.is_(True)).order_by(Profile.sort_order)
                )
            )
            .scalars()
            .all()
        )
        active_profile_id = await get_setting(session, "active_profile_id")
        if isinstance(active_profile_id, str) and active_profile_id:
            profiles = [profile for profile in profiles if profile.id == active_profile_id]
        if not profiles:
            raise EngineError("no client profile is configured", "no_profile", 400)
        # Key by database id, not display name: profile names are not unique.
        groups = [
            (profile.id, profile.name, endpoints_from_profile(profile, self.store))
            for profile in profiles
        ]
        endpoints, tag_mapping = namespace_endpoint_tags(groups)
        if not endpoints:
            raise EngineError("no client profile is configured", "no_profile", 400)
        chosen = selected
        if chosen is None:
            source = next((profile for profile in profiles if profile.selected_endpoint), None)
            if source is not None and source.selected_endpoint:
                chosen = tag_mapping.get((source.id, source.selected_endpoint))
        tags = {endpoint.tag for endpoint in endpoints}
        if chosen is not None and chosen not in tags:
            chosen = None
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
        downloaded = {
            ruleset.name: resolve_path(self.settings, ruleset.path)
            for ruleset in rule_sets
            if ruleset.path
        }
        for rule in rules:
            references = (rule.match_json or {}).get("rule_set", [])
            if isinstance(references, str):
                references = [references]
            missing = [name for name in references if name not in downloaded]
            if missing:
                raise EngineError(
                    "download the referenced rule set(s) before applying: "
                    + ", ".join(str(name) for name in missing),
                    "rule_set_not_downloaded",
                    400,
                )
        effective_mode = mode or self.settings.mode.value
        effective_tun = self.settings.tun_enabled if tun_enabled is None else tun_enabled
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
                    "path": str(resolve_path(self.settings, ruleset.path) or ""),
                }
                for ruleset in rule_sets
            ],
            tun=ClientTunSpec(
                enabled=effective_tun,
                interface_name=self.settings.tun_interface,
                mtu=self.settings.tun_mtu,
                stack=self.settings.tun_stack,
            ),
            clash_secret=self._clash_secret(),
            log_level=self.settings.log_level,
            ipv6=True,
            cache_path=str(self.settings.paths.data_dir / "cache.db"),
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
