"""Forms for the custom console."""

from __future__ import annotations

from django import forms
from django.conf import settings as django_settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ostium.certificates.models import Certificate
from ostium.formatting import format_bytes
from ostium.proxy.models import Inbound, ProxyUser
from ostium.proxy.services import parse_size


class UserEditForm(forms.ModelForm):
    quota = forms.CharField(
        label=_("Quota"),
        required=False,
        help_text=_("Examples: 100G, 1.5T. Leave empty or 0 for unlimited."),
    )
    expires_at = forms.DateTimeField(
        label=_("Expires at"),
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"],
        help_text=_("Leave empty for no expiry."),
    )

    class Meta:
        model = ProxyUser
        fields = ("name", "enabled", "quota_cycle", "note")
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["quota"].initial = (
                format_bytes(self.instance.quota_bytes, 0) if self.instance.quota_bytes else ""
            )
            if self.instance.expires_at:
                self.fields["expires_at"].initial = timezone.localtime(self.instance.expires_at).strftime(
                    "%Y-%m-%dT%H:%M"
                )
        self.fields["quota"].widget.attrs.update({"placeholder": "100G", "inputmode": "text"})

    def clean_name(self) -> str:
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError(_("Name must not be blank."))
        duplicate = ProxyUser.objects.filter(name=name).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError(_("Another user already uses this name."))
        return name

    def clean_quota(self) -> int:
        value = (self.cleaned_data.get("quota") or "").strip()
        if not value:
            return 0
        try:
            return parse_size(value)
        except ValueError as exc:
            raise forms.ValidationError(_("Use a size such as 100G or 1.5T.")) from exc

    def save(self, commit: bool = True) -> ProxyUser:
        user = super().save(commit=False)
        user.quota_bytes = self.cleaned_data["quota"]
        if commit:
            user.save()
        return user


class InboundForm(forms.ModelForm):
    class Meta:
        model = Inbound
        fields = ("enabled", "listen", "port", "certificate")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["certificate"].queryset = Certificate.objects.order_by("domain")
        self.fields["certificate"].required = False
        self.fields["certificate"].empty_label = _("No certificate")

    def clean_port(self) -> int:
        port = self.cleaned_data["port"]
        if not 1 <= port <= 65535:
            raise forms.ValidationError(_("Port must be between 1 and 65535."))
        return port

    def clean(self):
        cleaned = super().clean()
        enabled = cleaned.get("enabled")
        certificate = cleaned.get("certificate")
        if enabled and self.instance.needs_certificate and certificate is None:
            self.add_error("certificate", _("This protocol requires a certificate before it can be enabled."))
        if certificate is not None and not certificate.is_ready:
            self.add_error("certificate", _("The selected certificate is not ready."))
        return cleaned


class SettingsForm(forms.Form):
    PRIORITY = [
        "server_name",
        "public_host",
        "public_base_url",
        "subscription_update_interval",
        "server_dns_mode",
        "server_dns_doh_url",
        "block_private_egress",
        "log_level",
        "maintenance_mode",
        "webhook_url",
        "webhook_secret",
        "traffic_retention_days",
        "audit_retention_days",
        "auto_backup_enabled",
        "auto_backup_keep",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from constance import config

        for key in self.PRIORITY:
            definition = django_settings.CONSTANCE_CONFIG.get(key)
            if definition is None:
                continue
            _default, help_text, value_type = definition
            initial = getattr(config, key)
            label = key.replace("_", " ").capitalize()
            if value_type is bool:
                field = forms.BooleanField(label=label, required=False, initial=bool(initial), help_text=help_text)
            elif value_type is int:
                field = forms.IntegerField(label=label, initial=int(initial), help_text=help_text)
            elif key == "server_dns_mode":
                field = forms.ChoiceField(
                    label=label,
                    initial=initial,
                    choices=[("auto", "Auto"), ("doh", "DoH only"), ("udp", "UDP")],
                    help_text=help_text,
                )
            elif key in {"webhook_secret"}:
                field = forms.CharField(
                    label=label,
                    initial=initial,
                    required=False,
                    widget=forms.PasswordInput(render_value=True),
                    help_text=help_text,
                )
            elif key == "log_level":
                field = forms.ChoiceField(
                    label=label,
                    initial=initial,
                    choices=[(level, level) for level in ("trace", "debug", "info", "warn", "error")],
                    help_text=help_text,
                )
            else:
                field = forms.CharField(label=label, initial=initial, required=False, help_text=help_text)
            self.fields[key] = field

    def clean_server_dns_doh_url(self) -> str:
        value = self.cleaned_data.get("server_dns_doh_url", "")
        if value and not value.startswith("https://"):
            raise forms.ValidationError(_("DoH URL must use https://."))
        return value

    def clean_webhook_url(self) -> str:
        value = self.cleaned_data.get("webhook_url", "")
        if value and not value.startswith("https://"):
            raise forms.ValidationError(_("Webhook URL must use https://."))
        return value

    def clean_public_base_url(self) -> str:
        value = (self.cleaned_data.get("public_base_url") or "").rstrip("/")
        if value and not value.startswith(("https://", "http://")):
            raise forms.ValidationError(_("Public base URL must include a scheme."))
        return value

    def save(self) -> list[str]:
        from constance import config

        updated = []
        for key in self.fields:
            setattr(config, key, self.cleaned_data[key])
            updated.append(key)
        return updated


class BackupForm(forms.Form):
    password = forms.CharField(
        label=_("Backup password"),
        min_length=12,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=_("At least 12 characters. Store it outside this server."),
    )
    note = forms.CharField(label=_("Note"), max_length=200, required=False)
