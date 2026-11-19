"""Proxy app configuration and config-revision signal wiring."""

from __future__ import annotations

from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save


class ProxyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ostium.proxy"
    verbose_name = "代理"

    def ready(self) -> None:
        from auditlog.registry import auditlog

        from .models import Inbound, ProxyUser

        auditlog.register(
            ProxyUser,
            exclude_fields=["password_enc", "ss_password_enc", "subscription_token_enc", "subscription_token_hash"],
        )
        auditlog.register(Inbound, exclude_fields=["params_enc"])

        user_fields = {
            "name",
            "enabled",
            "uuid",
            "password_enc",
            "ss_password_enc",
            "expires_at",
            "quota_bytes",
            "quota_cycle",
            "disabled_reason",
        }

        def bump_for_user(sender, instance, **kwargs):
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and not (set(update_fields) & user_fields):
                return
            self._bump()

        def bump_for_inbound(sender, instance, **kwargs):
            self._bump()

        post_save.connect(bump_for_user, sender=ProxyUser, dispatch_uid="ostium.proxy_user_changed", weak=False)
        post_delete.connect(bump_for_user, sender=ProxyUser, dispatch_uid="ostium.proxy_user_deleted", weak=False)
        post_save.connect(bump_for_inbound, sender=Inbound, dispatch_uid="ostium.inbound_changed", weak=False)
        post_delete.connect(bump_for_inbound, sender=Inbound, dispatch_uid="ostium.inbound_deleted", weak=False)

    @staticmethod
    def _bump() -> None:
        from django.db.utils import OperationalError, ProgrammingError

        from .services import mark_dirty

        try:
            mark_dirty()
        except OperationalError, ProgrammingError:
            # Migrations and initial test database creation may not have the
            # runtime table yet; the next explicit apply will catch up.
            pass
