"""TLS certificate inventory."""

from __future__ import annotations

import uuid
from pathlib import Path

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ostium import paths


def _certificate_dir(domain: str) -> str:
    return f"certs/{domain}"


class Certificate(models.Model):
    class Status(models.TextChoices):
        READY = "ready", _("Ready")
        EXPIRED = "expired", _("Expired")
        INVALID = "invalid", _("Invalid")

    class Source(models.TextChoices):
        CERTBOT = "certbot", _("certbot")
        MANUAL = "manual", _("Manual import")
        SELF_SIGNED = "self_signed", _("Self-signed")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain = models.CharField(max_length=253, unique=True)
    cert_path = models.CharField(max_length=500, editable=False)
    key_path = models.CharField(max_length=500, editable=False)
    issuer = models.CharField(max_length=300, blank=True)
    subject = models.CharField(max_length=300, blank=True)
    expires_at = models.DateTimeField()
    fingerprint_sha256 = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.READY)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    auto_renew = models.BooleanField(default=False, help_text=_("Managed externally by certbot"))
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("domain",)
        verbose_name = _("certificate")
        verbose_name_plural = _("certificates")

    def __str__(self) -> str:
        return self.domain

    @property
    def cert_file(self) -> Path:
        return paths.data_dir() / self.cert_path

    @property
    def key_file(self) -> Path:
        return paths.data_dir() / self.key_path

    @property
    def days_remaining(self) -> int:
        return max(0, (self.expires_at - timezone.now()).days)

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    @property
    def is_ready(self) -> bool:
        return (
            self.status == self.Status.READY
            and not self.is_expired
            and self.cert_file.is_file()
            and self.key_file.is_file()
        )

    @property
    def expiry_tone(self) -> str:
        if self.is_expired:
            return "danger"
        if self.days_remaining <= 14:
            return "danger"
        if self.days_remaining <= 30:
            return "warning"
        return "success"
