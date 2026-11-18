"""DRF serializers for the control-plane API."""

from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers

from ostium.certificates.models import Certificate
from ostium.operations.models import Alert, AuditEvent, Backup
from ostium.proxy.models import Inbound, ProxyUser, TrafficDaily
from ostium.proxy.services import create_proxy_user


class ProxyUserSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True)
    quota_percent = serializers.FloatField(read_only=True)
    remaining_bytes = serializers.IntegerField(read_only=True)
    is_online = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProxyUser
        fields = (
            "id",
            "name",
            "enabled",
            "uuid",
            "expires_at",
            "quota_bytes",
            "quota_cycle",
            "used_bytes",
            "quota_percent",
            "remaining_bytes",
            "status",
            "disabled_reason",
            "note",
            "last_seen_at",
            "is_online",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "uuid",
            "used_bytes",
            "status",
            "disabled_reason",
            "last_seen_at",
            "created_at",
            "updated_at",
        )


class ProxyUserCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=64)
    quota_bytes = serializers.IntegerField(min_value=0, default=0)
    quota_cycle = serializers.ChoiceField(choices=ProxyUser.QuotaCycle.choices, default=ProxyUser.QuotaCycle.TOTAL)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    enabled = serializers.BooleanField(default=True)

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name must not be blank.")
        if ProxyUser.objects.filter(name=value).exists():
            raise serializers.ValidationError("A user with this name already exists.")
        return value

    def validate_expires_at(self, value):
        if value is not None and value <= timezone.now():
            raise serializers.ValidationError("Expiry must be in the future.")
        return value

    def create(self, validated_data):
        user, _token = create_proxy_user(**validated_data)
        return user


class InboundSerializer(serializers.ModelSerializer):
    label = serializers.CharField(read_only=True)
    validation_errors = serializers.ListField(child=serializers.CharField(), read_only=True)
    certificate_domain = serializers.CharField(write_only=True, required=False, allow_null=True, allow_blank=True)
    certificate = serializers.SlugRelatedField(slug_field="domain", read_only=True)
    public_params = serializers.SerializerMethodField()

    class Meta:
        model = Inbound
        fields = (
            "id",
            "kind",
            "label",
            "enabled",
            "listen",
            "port",
            "certificate",
            "certificate_domain",
            "public_params",
            "validation_errors",
            "updated_at",
        )
        read_only_fields = ("id", "kind", "label", "updated_at")

    def get_public_params(self, obj: Inbound) -> dict:
        params = obj.params
        if obj.kind == Inbound.Kind.VLESS:
            return {
                "public_key": params.get("public_key"),
                "short_id": params.get("short_id"),
                "server_name": params.get("server_name"),
            }
        if obj.kind == Inbound.Kind.SHADOWSOCKS:
            return {"method": params.get("method")}
        if obj.kind == Inbound.Kind.HYSTERIA2:
            return {"obfs": bool(params.get("obfs_password"))}
        return {}

    def validate(self, attrs):
        certificate_domain = attrs.pop("certificate_domain", serializers.empty)
        if certificate_domain is not serializers.empty:
            if certificate_domain:
                certificate = Certificate.objects.filter(domain=certificate_domain).first()
                if certificate is None:
                    raise serializers.ValidationError({"certificate_domain": "Certificate not found."})
                if not certificate.is_ready:
                    raise serializers.ValidationError({"certificate_domain": "Certificate is not ready."})
                attrs["certificate"] = certificate
            else:
                attrs["certificate"] = None
        instance = self.instance
        if instance is not None and instance.needs_certificate and not attrs.get("certificate", instance.certificate):
            raise serializers.ValidationError({"certificate_domain": "This protocol requires a certificate."})
        return attrs


class TrafficDailySerializer(serializers.ModelSerializer):
    total = serializers.IntegerField(read_only=True)

    class Meta:
        model = TrafficDaily
        fields = ("day", "uplink", "downlink", "total")


class CertificateSerializer(serializers.ModelSerializer):
    days_remaining = serializers.IntegerField(read_only=True)
    ready = serializers.BooleanField(source="is_ready", read_only=True)

    class Meta:
        model = Certificate
        fields = (
            "id",
            "domain",
            "issuer",
            "subject",
            "expires_at",
            "days_remaining",
            "status",
            "source",
            "auto_renew",
            "fingerprint_sha256",
            "ready",
            "last_error",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "issuer",
            "subject",
            "expires_at",
            "status",
            "source",
            "fingerprint_sha256",
            "created_at",
            "updated_at",
        )


class CertificateImportSerializer(serializers.Serializer):
    domain = serializers.CharField(max_length=253)
    certificate = serializers.CharField()
    private_key = serializers.CharField()
    auto_renew = serializers.BooleanField(default=False)


class AlertSerializer(serializers.ModelSerializer):
    acknowledged = serializers.BooleanField(read_only=True)

    class Meta:
        model = Alert
        fields = (
            "id",
            "level",
            "code",
            "message",
            "detail",
            "acknowledged",
            "acknowledged_at",
            "first_seen_at",
            "last_seen_at",
        )


class AuditEventSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.username", read_only=True, default=None)

    class Meta:
        model = AuditEvent
        fields = ("id", "actor", "action", "target", "ip", "detail", "created_at")


class BackupSerializer(serializers.ModelSerializer):
    created_by = serializers.CharField(source="created_by.username", read_only=True, default=None)

    class Meta:
        model = Backup
        fields = (
            "id",
            "filename",
            "size",
            "sha256",
            "encrypted",
            "note",
            "created_at",
            "restored_at",
            "created_by",
        )
