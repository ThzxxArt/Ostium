"""Operational state: runtime revision, alerts, audit trail and backups."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class RuntimeState(models.Model):
    """Singleton row describing the desired and applied data-plane state."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    desired_revision = models.PositiveBigIntegerField(default=0)
    applied_revision = models.PositiveBigIntegerField(default=0)
    config_sha256 = models.CharField(max_length=64, blank=True)
    singbox_pid = models.IntegerField(null=True, blank=True)
    singbox_running = models.BooleanField(default=False)
    singbox_started_at = models.DateTimeField(null=True, blank=True)
    dns_mode_effective = models.CharField(max_length=16, blank=True)
    last_error = models.TextField(blank=True)
    worker_heartbeat = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("runtime state")
        verbose_name_plural = _("runtime state")

    def __str__(self) -> str:
        return f"rev {self.applied_revision}/{self.desired_revision}"

    @classmethod
    def load(cls) -> RuntimeState:
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    def mark_desired(cls) -> int:
        obj = cls.load()
        cls.objects.filter(pk=obj.pk).update(desired_revision=models.F("desired_revision") + 1)
        obj.refresh_from_db(fields=["desired_revision"])
        return obj.desired_revision

    @property
    def heartbeat_age(self) -> float | None:
        if not self.worker_heartbeat:
            return None
        return (timezone.now() - self.worker_heartbeat).total_seconds()

    @property
    def worker_alive(self) -> bool:
        age = self.heartbeat_age
        return age is not None and age < settings.OSTIUM_WORKER_HEARTBEAT_TIMEOUT

    @property
    def is_converged(self) -> bool:
        return self.applied_revision >= self.desired_revision and self.singbox_running


class Alert(models.Model):
    class Level(models.TextChoices):
        INFO = "info", _("Info")
        WARNING = "warning", _("Warning")
        CRITICAL = "critical", _("Critical")

    level = models.CharField(max_length=10, choices=Level.choices, default=Level.WARNING)
    code = models.CharField(max_length=64)
    fingerprint = models.CharField(max_length=160, unique=True)
    message = models.TextField()
    detail = models.JSONField(default=dict, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-last_seen_at",)
        indexes = [models.Index(fields=["code", "acknowledged_at"])]
        verbose_name = _("alert")
        verbose_name_plural = _("alerts")

    def __str__(self) -> str:
        return f"[{self.level}] {self.code}"

    @property
    def acknowledged(self) -> bool:
        return self.acknowledged_at is not None


class AuditEvent(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ostium_audit_events",
    )
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=200, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["action", "created_at"])]
        verbose_name = _("audit event")
        verbose_name_plural = _("audit events")

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"


class Backup(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    filename = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    encrypted = models.BooleanField(default=True)
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ostium_backups",
    )
    created_at = models.DateTimeField(default=timezone.now)
    restored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = _("backup")
        verbose_name_plural = _("backups")

    def __str__(self) -> str:
        return self.filename
