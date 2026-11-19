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
        label="流量配额",
        required=False,
        help_text="例如 100G、1.5T；留空或 0 表示不限。",
    )
    expires_at = forms.DateTimeField(
        label="到期时间",
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"],
        help_text="留空表示永不过期。",
    )

    class Meta:
        model = ProxyUser
        fields = ("name", "enabled", "quota_cycle", "note")
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            # Prefer a human-readable value, but fall back to the exact byte
            # count when the formatted value would round it.
            quota = self.instance.quota_bytes
            if quota:
                rendered = format_bytes(quota, 1)
                try:
                    self.fields["quota"].initial = rendered if parse_size(rendered) == quota else str(quota)
                except ValueError:
                    self.fields["quota"].initial = str(quota)
            else:
                self.fields["quota"].initial = ""
            if self.instance.expires_at:
                self.fields["expires_at"].initial = timezone.localtime(self.instance.expires_at).strftime(
                    "%Y-%m-%dT%H:%M"
                )
        self.fields["quota_cycle"].choices = [
            (ProxyUser.QuotaCycle.TOTAL, "总量"),
            (ProxyUser.QuotaCycle.MONTHLY, "每月重置"),
        ]
        self.fields["quota"].widget.attrs.update({"placeholder": "100G", "inputmode": "text"})

    def clean_name(self) -> str:
        from ostium.proxy.models import validate_user_name

        try:
            name = validate_user_name(self.cleaned_data["name"])
        except Exception as exc:
            raise forms.ValidationError(str(exc)) from exc
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
        self.fields["certificate"].empty_label = "未选择证书"

    def clean_port(self) -> int:
        port = self.cleaned_data["port"]
        if not 1 <= port <= 65535:
            raise forms.ValidationError("端口必须在 1–65535 之间。")
        return port

    def clean(self):
        cleaned = super().clean()
        enabled = cleaned.get("enabled")
        certificate = cleaned.get("certificate")
        if enabled and self.instance.needs_certificate and certificate is None:
            self.add_error("certificate", "启用这条线路前必须先分配证书。")
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
    LABELS = {
        "server_name": "服务器名称",
        "public_host": "公开主机名",
        "public_base_url": "公开访问地址",
        "subscription_update_interval": "订阅更新间隔（小时）",
        "server_dns_mode": "服务器 DNS 模式",
        "server_dns_doh_url": "DoH 地址",
        "block_private_egress": "阻止私网出口",
        "log_level": "日志级别",
        "maintenance_mode": "维护模式",
        "webhook_url": "Webhook 地址",
        "webhook_secret": "Webhook 密钥",
        "traffic_retention_days": "流量记录保留天数",
        "audit_retention_days": "审计记录保留天数",
        "auto_backup_enabled": "启用自动备份",
        "auto_backup_keep": "自动备份保留份数",
    }
    HELP_TEXTS = {
        "server_name": "显示在订阅标题和控制台中的服务器名称。",
        "public_host": "订阅中点显示的公开域名或 IP，不含端口。",
        "public_base_url": "控制台公开 HTTPS 地址；使用 SSH 隧道时留空。",
        "subscription_update_interval": "客户端两次拉取订阅之间的间隔，1–720 小时。",
        "server_dns_mode": "auto 探测 DoH 失败时回退 UDP；doh 失败拒绝应用；udp 不探测。",
        "server_dns_doh_url": "数据面使用的 DNS-over-HTTPS 地址，必须是 HTTPS。",
        "block_private_egress": "阻止 RFC1918、CGNAT、回环、链路本地和云 metadata 目标。",
        "log_level": "sing-box 日志级别：trace、debug、info、warn、error。",
        "maintenance_mode": "暂停配置应用，并在控制台显示维护横幅。",
        "webhook_url": "可选的告警 Webhook，必须是 HTTPS。",
        "webhook_secret": "用于 HMAC-SHA256 签名；留空保持当前密钥。",
        "traffic_retention_days": "每日流量历史保留天数。",
        "audit_retention_days": "审计事件保留天数。",
        "auto_backup_enabled": "每天自动创建加密备份。",
        "auto_backup_keep": "自动备份保留份数。",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from constance import config

        for key in self.PRIORITY:
            definition = django_settings.CONSTANCE_CONFIG.get(key)
            if definition is None:
                continue
            _default, _help_text, value_type = definition
            initial = getattr(config, key)
            label = self.LABELS.get(key, key.replace("_", " ").capitalize())
            help_text = self.HELP_TEXTS.get(key, "")
            if value_type is bool:
                field = forms.BooleanField(label=label, required=False, initial=bool(initial), help_text=help_text)
            elif value_type is int:
                field = forms.IntegerField(label=label, initial=int(initial), help_text=help_text)
            elif key == "server_dns_mode":
                field = forms.ChoiceField(
                    label=label,
                    initial=initial,
                    choices=[("auto", "自动（探测 DoH）"), ("doh", "仅 DoH"), ("udp", "仅 UDP")],
                    help_text=help_text,
                )
            elif key in {"webhook_secret"}:
                field = forms.CharField(
                    label=label,
                    initial="",
                    required=False,
                    widget=forms.PasswordInput(render_value=False),
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

    def clean(self):
        from ostium.operations.runtime_settings import SettingValidationError, coerce_setting

        cleaned = super().clean()
        for key, value in list(cleaned.items()):
            if key == "webhook_secret" and not value:
                continue
            try:
                cleaned[key] = coerce_setting(key, value)
            except SettingValidationError as exc:
                self.add_error(key, str(exc))
        return cleaned

    def save(self) -> list[str]:
        from constance import config

        updated = []
        for key in self.fields:
            value = self.cleaned_data.get(key)
            if key == "webhook_secret" and not value:
                continue
            setattr(config, key, value)
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
