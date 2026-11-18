"""Admin for TLS certificates."""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from ostium.operations.services import record_audit

from .models import Certificate
from .services import import_certificate, refresh_status


class CertificateImportForm(forms.Form):
    domain = forms.CharField(max_length=253, label=_("Domain"))
    certificate = forms.CharField(widget=forms.Textarea(attrs={"rows": 8}), label=_("Certificate PEM"))
    private_key = forms.CharField(widget=forms.Textarea(attrs={"rows": 8}), label=_("Private key PEM"))
    auto_renew = forms.BooleanField(required=False, label=_("Managed by certbot"))


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
        from django.core.exceptions import PermissionDenied

        if not request.user.is_superuser:
            raise PermissionDenied
        form = CertificateImportForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            try:
                certificate = import_certificate(
                    domain=form.cleaned_data["domain"],
                    cert_pem=form.cleaned_data["certificate"],
                    key_pem=form.cleaned_data["private_key"],
                    auto_renew=form.cleaned_data["auto_renew"],
                    actor=request.user,
                )
            except Exception as exc:
                form.add_error(None, str(exc))
            else:
                record_audit(action="certificate.imported", request=request, target=certificate.domain)
                messages.success(request, _("Certificate imported for %(domain)s.") % {"domain": certificate.domain})
                return redirect("admin:certificates_certificate_changelist")
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": _("Import certificate"),
            "form": form,
        }
        return render(request, "admin/certificates/certificate/import.html", context)

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
