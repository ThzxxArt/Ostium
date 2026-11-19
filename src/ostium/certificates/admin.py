"""Admin for TLS certificates."""

from __future__ import annotations

from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from .models import Certificate
from .services import refresh_status


@admin.register(Certificate)
class CertificateAdmin(ModelAdmin):
    list_display = (
        "domain",
        "status_badge",
        "expires_at",
        "days_remaining",
        "source",
        "auto_renew",
        "inbound_count",
    )
    list_filter = ("status", "source", "auto_renew")
    search_fields = ("domain", "issuer", "subject")
    readonly_fields = (
        "domain",
        "issuer",
        "subject",
        "expires_at",
        "days_remaining",
        "fingerprint_sha256",
        "status",
        "cert_path",
        "key_path",
        "last_error",
        "created_at",
        "updated_at",
    )
    actions = ("refresh_certificates",)

    def has_add_permission(self, request) -> bool:
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "import/",
                self.admin_site.admin_view(self.import_view),
                name="certificates_certificate_import",
            )
        ]
        return custom + urls

    def import_view(self, request):
        # The console has a first-class Aurora import page. Keep the old admin
        # URL as a redirect for bookmarks and dashboard links.
        return redirect("console:certificate_import")

    @admin.display(description=_("Expires in"))
    def days_remaining(self, obj: Certificate):
        if not obj.pk:
            return "—"
        return _("%(days)s days") % {"days": obj.days_remaining}

    @admin.display(description=_("Status"))
    def status_badge(self, obj: Certificate):
        tone = {
            "success": "ostium-badge--success",
            "warning": "ostium-badge--warning",
            "danger": "ostium-badge--danger",
        }[obj.expiry_tone]
        return format_html('<span class="ostium-badge {}">{}</span>', tone, obj.get_status_display())

    @admin.display(description=_("Inbounds"))
    def inbound_count(self, obj: Certificate):
        return obj.inbounds.count()

    @admin.action(description=_("Re-validate selected certificates"))
    def refresh_certificates(self, request, queryset):
        for certificate in queryset:
            refresh_status(certificate)
        self.message_user(request, _("%(count)d certificate(s) re-validated.") % {"count": queryset.count()})
