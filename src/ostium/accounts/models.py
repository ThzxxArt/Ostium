"""Account models: administrator profile and scoped API keys."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework_api_key.models import AbstractAPIKey


class AdminProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ostium_profile",
        verbose_name=_("user"),
    )
    must_change_password = models.BooleanField(default=False, verbose_name=_("must change password"))
    totp_required = models.BooleanField(default=True, verbose_name=_("TOTP required"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("administrator profile")
        verbose_name_plural = _("administrator profiles")

    def __str__(self) -> str:
        return f"Profile<{self.user}>"


class ApiKey(AbstractAPIKey):
    """Scoped API key issued to automation.

    The plaintext key is shown exactly once at creation. Only a keyed hash is
    persisted by ``djangorestframework-api-key``.
    """

    class Scope(models.TextChoices):
        READ = "read", _("Read only")
        WRITE = "write", _("Read and write")

    scope = models.CharField(max_length=8, choices=Scope.choices, default=Scope.READ)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_used_ip = models.GenericIPAddressField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ostium_api_keys",
    )

    class Meta(AbstractAPIKey.Meta):
        verbose_name = _("API key")
        verbose_name_plural = _("API keys")

    @property
    def can_write(self) -> bool:
        return self.scope == self.Scope.WRITE

    def touch(self, ip: str | None = None) -> None:
        ApiKey.objects.filter(pk=self.pk).update(last_used_at=timezone.now(), last_used_ip=ip)


__all__ = ["AdminProfile", "ApiKey"]
