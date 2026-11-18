"""Admin for proxy users and inbounds."""

from __future__ import annotations

from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from ostium.operations.services import record_audit
from ostium.subscriptions.services import (
    masked_token,
    qr_data_uri,
    subscription_links,
    subscription_url,
    userinfo_header,
)

from .models import Inbound, ProxyUser, StatsEpoch, TrafficDaily


def _status_class(status: str) -> str:
    return {
        "active": "ostium-badge ostium-badge--success",
        "disabled": "ostium-badge ostium-badge--muted",
        "expired": "ostium-badge ostium-badge--warning",
        "quota_exceeded": "ostium-badge ostium-badge--danger",
    }.get(status, "ostium-badge")


@admin.register(ProxyUser)
class ProxyUserAdmin(ModelAdmin):
    list_display = ("name", "status_badge", "quota_usage", "expires_at", "last_seen_at", "enabled")
    list_filter = ("enabled", "quota_cycle", "created_at")
    search_fields = ("name", "note")
    ordering = ("name",)
    date_hierarchy = "created_at"
    readonly_fields = (
        "uuid",
        "used_bytes",
        "cycle_started_at",
        "created_at",
        "updated_at",
        "subscription_panel",
    )
    fieldsets = (
        (_("Identity"), {"fields": ("name", "enabled", "note")}),
        (
            _("Quota and expiry"),
            {"fields": ("quota_bytes", "quota_cycle", "expires_at", "used_bytes", "cycle_started_at")},
        ),
        (_("Credentials"), {"fields": ("uuid", "subscription_panel")}),
        (_("Timestamps"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    actions = (
        "enable_users",
        "disable_users",
        "rotate_subscriptions",
        "rotate_credentials",
        "reset_usage",
    )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<uuid:object_id>/subscription/",
                self.admin_site.admin_view(self.subscription_view),
                name="proxy_proxyuser_subscription",
            )
        ]
        return custom + urls

    def subscription_view(self, request, object_id):
        from django.core.exceptions import PermissionDenied

        user = get_object_or_404(ProxyUser, pk=object_id)
        if not self.has_view_permission(request, user):
            raise PermissionDenied
        if request.method == "POST" and not self.has_change_permission(request, user):
            raise PermissionDenied
        revealed = False
        if request.method == "POST":
            action_name = request.POST.get("action")
            if action_name == "reveal":
                revealed = True
                record_audit(action="subscription.revealed", request=request, target=user.name)
            elif action_name == "rotate":
                user.rotate_subscription_token()
                record_audit(action="subscription.rotated", request=request, target=user.name)
                messages.success(request, _("Subscription token rotated. Old URLs no longer work."))
                return redirect(request.path)
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": user,
            "title": _("Subscription · %(name)s") % {"name": user.name},
            "revealed": revealed,
            "token": user.reveal_subscription_token() if revealed else masked_token(user),
            "links": subscription_links(user, request) if revealed else [],
            "qr": qr_data_uri(subscription_url(user, "base64", request)) if revealed else "",
            "userinfo": userinfo_header(user),
        }
        return render(request, "admin/proxy/proxyuser/subscription.html", context)

    @admin.display(description=_("Status"))
    def status_badge(self, obj: ProxyUser):
        labels = {
            "active": _("Active"),
            "disabled": _("Disabled"),
            "expired": _("Expired"),
            "quota_exceeded": _("Quota exceeded"),
        }
        return format_html('<span class="{}">{}</span>', _status_class(obj.status), labels.get(obj.status, obj.status))

    @admin.display(description=_("Quota"))
    def quota_usage(self, obj: ProxyUser):
        if obj.quota_bytes <= 0:
            return format_html('<span class="ostium-muted">{} / ∞</span>', obj.used_bytes)
        percent = obj.quota_percent or 0
        return format_html(
            '<span class="ostium-quota"><span class="ostium-quota__bar">'
            '<span style="width:{}%"></span></span>{}%</span>',
            percent,
            percent,
        )

    @admin.display(description=_("Subscription"))
    def subscription_panel(self, obj: ProxyUser):
        if not obj.pk:
            return "—"
        url = reverse("admin:proxy_proxyuser_subscription", args=[obj.pk])
        return format_html('<a class="ostium-button" href="{}">{}</a>', url, _("Open subscription panel"))

    @admin.action(description=_("Enable selected users"))
    def enable_users(self, request, queryset):
        for user in queryset:
            user.enable()
            record_audit(action="user.enabled", request=request, target=user.name)
        self.message_user(request, _("%(count)d user(s) enabled.") % {"count": queryset.count()})

    @admin.action(description=_("Disable selected users"))
    def disable_users(self, request, queryset):
        for user in queryset:
            user.disable()
            record_audit(action="user.disabled", request=request, target=user.name)
        self.message_user(request, _("%(count)d user(s) disabled.") % {"count": queryset.count()})

    @admin.action(description=_("Rotate subscription tokens"))
    def rotate_subscriptions(self, request, queryset):
        for user in queryset:
            user.rotate_subscription_token()
            record_audit(action="subscription.rotated", request=request, target=user.name)
        self.message_user(request, _("%(count)d subscription token(s) rotated.") % {"count": queryset.count()})

    @admin.action(description=_("Rotate credentials"))
    def rotate_credentials(self, request, queryset):
        for user in queryset:
            user.rotate_credentials()
            record_audit(action="user.credentials_rotated", request=request, target=user.name)
        self.message_user(request, _("%(count)d credential set(s) rotated.") % {"count": queryset.count()})

    @admin.action(description=_("Reset usage counters"))
    def reset_usage(self, request, queryset):
        for user in queryset:
            user.reset_usage()
            record_audit(action="user.usage_reset", request=request, target=user.name)
        self.message_user(request, _("%(count)d usage counter(s) reset.") % {"count": queryset.count()})


@admin.register(Inbound)
class InboundAdmin(ModelAdmin):
    list_display = ("kind", "short_label", "enabled", "listen", "port", "certificate", "status_hint")
    list_filter = ("enabled", "kind")
    readonly_fields = ("params_summary", "validation_summary", "created_at", "updated_at")
    fieldsets = (
        (_("Inbound"), {"fields": ("kind", "enabled", "listen", "port")}),
        (_("TLS"), {"fields": ("certificate",)}),
        (_("Protocol parameters"), {"fields": ("params_summary", "validation_summary")}),
        (_("Timestamps"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            return ("kind", *self.readonly_fields)
        return self.readonly_fields

    def save_model(self, request, obj, form, change):
        obj.ensure_defaults()
        super().save_model(request, obj, form, change)
        record_audit(action="inbound.updated", request=request, target=obj.kind)

    @admin.display(description=_("Parameters"))
    def params_summary(self, obj: Inbound):
        if not obj.pk:
            return "—"
        params = obj.params
        if obj.kind == Inbound.Kind.VLESS:
            return format_html(
                "<code>pbk={}</code><br><code>sid={}</code><br><code>sni={}</code>",
                params.get("public_key", "—"),
                params.get("short_id", "—"),
                params.get("server_name", "—"),
            )
        if obj.kind == Inbound.Kind.SHADOWSOCKS:
            return format_html("<code>{}</code>", params.get("method", "—"))
        if obj.kind == Inbound.Kind.HYSTERIA2:
            return _("Obfuscation: %(state)s") % {
                "state": _("enabled") if params.get("obfs_password") else _("disabled")
            }
        return "—"

    @admin.display(description=_("Validation"))
    def validation_summary(self, obj: Inbound):
        if not obj.pk:
            return "—"
        errors = obj.validation_errors()
        if not errors:
            return format_html('<span class="ostium-badge ostium-badge--success">{}</span>', _("Ready"))
        return format_html(
            '<span class="ostium-badge ostium-badge--warning">{}</span> {}',
            _("Needs attention"),
            "; ".join(errors),
        )

    @admin.display(description=_("State"))
    def status_hint(self, obj: Inbound):
        errors = obj.validation_errors()
        if not obj.enabled:
            return format_html('<span class="ostium-badge ostium-badge--muted">{}</span>', _("Disabled"))
        if errors:
            return format_html('<span class="ostium-badge ostium-badge--warning">{}</span>', _("Incomplete"))
        return format_html('<span class="ostium-badge ostium-badge--success">{}</span>', _("Enabled"))


@admin.register(TrafficDaily)
class TrafficDailyAdmin(ModelAdmin):
    list_display = ("user", "day", "uplink", "downlink", "total")
    list_filter = ("day",)
    search_fields = ("user__name",)
    readonly_fields = ("user", "day", "uplink", "downlink")

    @admin.display(description=_("Total"))
    def total(self, obj: TrafficDaily):
        return obj.total


@admin.register(StatsEpoch)
class StatsEpochAdmin(ModelAdmin):
    list_display = ("user", "epoch", "started_at", "ended_at", "active")
    list_filter = ("active",)
    search_fields = ("user__name",)
    readonly_fields = ("user", "epoch", "started_at", "ended_at", "active")
