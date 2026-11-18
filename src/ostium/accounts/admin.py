"""Admin registration for accounts."""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice
from unfold.admin import ModelAdmin

from .models import AdminProfile, ApiKey


class AdminProfileInline(admin.StackedInline):
    model = AdminProfile
    can_delete = False
    verbose_name_plural = _("Ostium profile")
    fields = ("must_change_password", "totp_required")


class TOTPDeviceInline(admin.TabularInline):
    model = TOTPDevice
    extra = 0
    fields = ("name", "confirmed", "last_used_at")
    readonly_fields = ("last_used_at",)
    can_delete = True


class StaticDeviceInline(admin.TabularInline):
    model = StaticDevice
    extra = 0
    fields = ("name", "confirmed", "last_used_at")
    readonly_fields = ("last_used_at",)
    can_delete = True


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class OstiumUserAdmin(BaseUserAdmin, ModelAdmin):
    inlines = [AdminProfileInline, TOTPDeviceInline, StaticDeviceInline]
    list_display = ("username", "is_active", "is_staff", "last_login", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("username", "email")
    ordering = ("username",)


@admin.register(ApiKey)
class ApiKeyAdmin(ModelAdmin):
    list_display = ("name", "prefix", "scope", "created", "expiry_date", "revoked", "last_used_at")
    list_filter = ("scope", "revoked")
    search_fields = ("name", "prefix")
    readonly_fields = ("id", "prefix", "hashed_key", "created", "last_used_at", "last_used_ip")
    fields = ("name", "scope", "created_by", "expiry_date", "revoked", "last_used_at", "last_used_ip")
    actions = ("revoke_keys",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return request.user.is_superuser

    @admin.action(description=_("Revoke selected API keys"))
    def revoke_keys(self, request, queryset):
        updated = queryset.update(revoked=True)
        self.message_user(request, _("%(count)d API key(s) revoked.") % {"count": updated})
