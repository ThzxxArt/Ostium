"""Admin for operational records."""

from __future__ import annotations

from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from ostium.operations.services import acknowledge_alert

from .models import Alert, AuditEvent, Backup, RuntimeState


@admin.register(RuntimeState)
class RuntimeStateAdmin(ModelAdmin):
    list_display = (
        "id",
        "desired_revision",
        "applied_revision",
        "singbox_running",
        "worker_heartbeat",
        "updated_at",
    )
    readonly_fields = (
        "id",
        "desired_revision",
        "applied_revision",
        "config_sha256",
        "singbox_pid",
        "singbox_running",
        "singbox_started_at",
        "dns_mode_effective",
        "last_error",
        "worker_heartbeat",
        "updated_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Alert)
class AlertAdmin(ModelAdmin):
    list_display = ("level", "code", "message", "acknowledged", "resolved_at", "last_seen_at")
    list_filter = ("level", "acknowledged_at", "resolved_at")
    search_fields = ("code", "message")
    readonly_fields = (
        "level",
        "code",
        "fingerprint",
        "message",
        "detail",
        "first_seen_at",
        "last_seen_at",
        "resolved_at",
    )
    actions = ("acknowledge",)

    @admin.display(boolean=True, description=_("Acknowledged"))
    def acknowledged(self, obj: Alert):
        return obj.acknowledged

    @admin.action(description=_("Acknowledge selected alerts"))
    def acknowledge(self, request, queryset):
        for alert in queryset:
            acknowledge_alert(alert)
        self.message_user(request, _("%(count)d alert(s) acknowledged.") % {"count": queryset.count()})


@admin.register(AuditEvent)
class AuditEventAdmin(ModelAdmin):
    list_display = ("created_at", "action", "actor", "target", "ip")
    list_filter = ("action", "created_at")
    search_fields = ("action", "target", "actor__username", "ip")
    readonly_fields = ("actor", "action", "target", "ip", "user_agent", "detail", "created_at")
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return request.user.is_superuser


@admin.register(Backup)
class BackupAdmin(ModelAdmin):
    def delete_model(self, request, obj) -> None:
        from .backup import delete_backup

        delete_backup(obj, actor=request.user)

    def delete_queryset(self, request, queryset) -> None:
        from .backup import delete_backup

        for backup in queryset:
            delete_backup(backup, actor=request.user)

    list_display = ("filename", "size", "encrypted", "created_at", "restored_at", "created_by")
    list_filter = ("encrypted", "created_at")
    search_fields = ("filename", "note")
    readonly_fields = (
        "id",
        "filename",
        "size",
        "sha256",
        "encrypted",
        "note",
        "created_by",
        "created_at",
        "restored_at",
    )

    def has_add_permission(self, request) -> bool:
        return False
