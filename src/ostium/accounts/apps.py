"""Account app configuration and signal wiring."""

from __future__ import annotations

from django.apps import AppConfig
from django.db.models.signals import post_save


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ostium.accounts"
    verbose_name = "Accounts"

    def ready(self) -> None:
        from django.contrib.auth import get_user_model

        from .models import AdminProfile

        def ensure_profile(sender, instance, created, **kwargs):
            if created:
                AdminProfile.objects.get_or_create(user=instance)

        post_save.connect(
            ensure_profile,
            sender=get_user_model(),
            dispatch_uid="ostium.ensure_profile",
            weak=False,
        )
