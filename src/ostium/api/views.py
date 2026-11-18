"""Control-plane REST API (``/api/v1``)."""

from __future__ import annotations

import os
from datetime import timedelta

from constance import config as runtime_config
from django.db.models import Sum
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from ostium.certificates.models import Certificate
from ostium.certificates.services import delete_certificate, import_certificate
from ostium.engine.clash import ClashClient, ClashError
from ostium.engine.runtime import read_usage
from ostium.operations.models import Alert, AuditEvent, Backup, RuntimeState
from ostium.operations.services import acknowledge_alert, record_audit
from ostium.proxy.models import Inbound, ProxyUser, TrafficDaily
from ostium.proxy.services import mark_dirty

from .serializers import (
    AlertSerializer,
    AuditEventSerializer,
    BackupSerializer,
    CertificateImportSerializer,
    CertificateSerializer,
    InboundSerializer,
    ProxyUserCreateSerializer,
    ProxyUserSerializer,
    TrafficDailySerializer,
)
from .views_helpers import subscription_payload


def _actor(request):
    """Resolve the audit/ownership actor for session or API-key requests."""

    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return user
    api_key = getattr(request, "api_key", None)
    return getattr(api_key, "created_by", None)


class UserViewSet(viewsets.ModelViewSet):
    queryset = ProxyUser.objects.all().order_by("name")
    serializer_class = ProxyUserSerializer
    lookup_field = "id"

    def get_serializer_class(self):
        if self.action == "create":
            return ProxyUserCreateSerializer
        return ProxyUserSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        record_audit(action="user.created", request=request, target=user.name)
        return Response(ProxyUserSerializer(user).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        user = serializer.save()
        record_audit(action="user.updated", request=self.request, target=user.name)

    def perform_destroy(self, instance):
        name = instance.name
        instance.delete()
        record_audit(action="user.deleted", request=self.request, target=name)

    @action(detail=True, methods=["post"])
    def rotate(self, request, id=None):
        user = self.get_object()
        user.rotate_credentials()
        record_audit(action="user.credentials_rotated", request=request, target=user.name)
        return Response({"detail": "Credentials rotated.", "user": ProxyUserSerializer(user).data})

    @action(detail=True, methods=["post"], url_path="reset-usage")
    def reset_usage(self, request, id=None):
        user = self.get_object()
        user.reset_usage()
        record_audit(action="user.usage_reset", request=request, target=user.name)
        return Response(ProxyUserSerializer(user).data)

    @action(detail=True, methods=["get"])
    def usage(self, request, id=None):
        user = self.get_object()
        rows = TrafficDaily.objects.filter(user=user).order_by("-day")[:30]
        usage = read_usage().get("users", {}).get(user.name, {})
        return Response(
            {
                "user": str(user.id),
                "used_bytes": user.used_bytes,
                "quota_bytes": user.quota_bytes,
                "quota_percent": user.quota_percent,
                "daily": TrafficDailySerializer(rows, many=True).data,
                "live": usage,
            }
        )

    @action(detail=True, methods=["get"])
    def subscription(self, request, id=None):
        user = self.get_object()
        return Response(subscription_payload(user, request, reveal=False))

    @action(detail=True, methods=["post"], url_path="subscription/reveal")
    def subscription_reveal(self, request, id=None):
        user = self.get_object()
        record_audit(action="subscription.revealed", request=request, target=user.name)
        return Response(subscription_payload(user, request, reveal=True))

    @action(detail=True, methods=["post"], url_path="subscription/rotate")
    def subscription_rotate(self, request, id=None):
        user = self.get_object()
        user.rotate_subscription_token()
        record_audit(action="subscription.rotated", request=request, target=user.name)
        return Response(subscription_payload(user, request, reveal=True))


class InboundViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Inbound.objects.select_related("certificate").all()
    serializer_class = InboundSerializer
    lookup_field = "kind"
    lookup_value_regex = "[a-z0-9]+"
    pagination_class = None

    def perform_update(self, serializer):
        inbound = serializer.save()
        record_audit(action="inbound.updated", request=self.request, target=inbound.kind)

    @action(detail=True, methods=["post"], url_path="reality-keys")
    def reality_keys(self, request, kind=None):
        inbound = self.get_object()
        if inbound.kind != Inbound.Kind.VLESS:
            return Response({"detail": "Only VLESS uses Reality keys."}, status=status.HTTP_400_BAD_REQUEST)
        inbound.rotate_keys()
        record_audit(action="inbound.reality_rotated", request=request, target=inbound.kind)
        params = inbound.params
        return Response({"public_key": params.get("public_key"), "short_id": params.get("short_id")})


class CertificateViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Certificate.objects.all()
    serializer_class = CertificateSerializer
    pagination_class = None

    def create(self, request, *args, **kwargs):
        serializer = CertificateImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            certificate = import_certificate(
                domain=data["domain"],
                cert_pem=data["certificate"],
                key_pem=data["private_key"],
                auto_renew=data["auto_renew"],
                actor=_actor(request),
            )
        except Exception as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        record_audit(action="certificate.imported", request=request, target=certificate.domain)
        return Response(CertificateSerializer(certificate).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        certificate = self.get_object()
        try:
            delete_certificate(certificate, actor=_actor(request))
        except Exception as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        certificate = self.get_object()
        if not certificate.is_ready:
            return Response({"detail": "Certificate is not ready."}, status=status.HTTP_400_BAD_REQUEST)
        kinds = request.data.get("inbounds", [])
        if not isinstance(kinds, list) or not kinds:
            return Response({"detail": "Provide a list of inbound kinds."}, status=status.HTTP_400_BAD_REQUEST)
        updated = []
        for inbound in Inbound.objects.filter(kind__in=kinds):
            if inbound.needs_certificate:
                inbound.certificate = certificate
                inbound.save(update_fields=["certificate", "updated_at"])
                updated.append(inbound.kind)
        record_audit(
            action="certificate.assigned",
            request=request,
            target=certificate.domain,
            detail={"kinds": updated},
        )
        return Response({"assigned": updated})


class StatsOverviewView(APIView):
    @extend_schema(responses=dict)
    def get(self, request):
        state = RuntimeState.load()
        usage = read_usage()
        today = TrafficDaily.objects.filter(day=timezone.localdate()).aggregate(up=Sum("uplink"), down=Sum("downlink"))
        return Response(
            {
                "users_total": ProxyUser.objects.count(),
                "users_active": ProxyUser.objects.filter(enabled=True).count(),
                "users_online": sum(1 for item in usage.get("users", {}).values() if item.get("online")),
                "today": {"uplink": today["up"] or 0, "downlink": today["down"] or 0},
                "runtime": {
                    "desired_revision": state.desired_revision,
                    "applied_revision": state.applied_revision,
                    "singbox_running": state.singbox_running,
                    "worker_alive": state.worker_alive,
                    "config_sha256": state.config_sha256,
                    "last_error": state.last_error[:1000],
                },
                "stats_ok": usage.get("stats_ok", False),
            }
        )


class StatsTrafficView(APIView):
    @extend_schema(
        parameters=[OpenApiParameter("days", int, default=7)],
        responses=OpenApiTypes.OBJECT,
    )
    def get(self, request):
        try:
            days = min(365, max(1, int(request.query_params.get("days", 7))))
        except ValueError:
            days = 7
        start = timezone.localdate() - timedelta(days=days - 1)
        rows = (
            TrafficDaily.objects.filter(day__gte=start)
            .values("day")
            .annotate(uplink=Sum("uplink"), downlink=Sum("downlink"))
            .order_by("day")
        )
        return Response({"days": days, "series": list(rows)})


class ConnectionsView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        try:
            return Response({"connections": ClashClient().connections()})
        except ClashError as exc:
            return Response({"connections": [], "detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    @extend_schema(request=None, responses={204: None}, operation_id="connections_close_all")
    def delete(self, request):
        try:
            ClashClient().close_all()
        except ClashError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        record_audit(action="connections.closed_all", request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConnectionDetailView(APIView):
    @extend_schema(request=None, responses={204: None}, operation_id="connection_close")
    def delete(self, request, connection_id: str):
        try:
            ClashClient().close_connection(connection_id)
        except ClashError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        record_audit(action="connection.closed", request=request, target=connection_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class JobSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    func = serializers.CharField()
    started = serializers.DateTimeField(allow_null=True)
    stopped = serializers.DateTimeField(allow_null=True)
    success = serializers.BooleanField(allow_null=True)
    result = serializers.CharField(allow_blank=True)
    group = serializers.CharField(allow_blank=True)


class JobViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = JobSerializer
    lookup_field = "id"

    def get_queryset(self):
        from django_q.models import Task

        return Task.objects.all().order_by("-started")

    @action(detail=True, methods=["post"])
    def cancel(self, request, id=None):
        from ostium.operations.services import cancel_queued_job

        if cancel_queued_job(id):
            record_audit(action="job.cancelled", request=request, target=id)
            return Response({"cancelled": 1})
        from django_q.models import Task

        task = Task.objects.filter(pk=id).first()
        if task is not None:
            return Response(
                {"detail": "This task has already started and cannot be cancelled."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({"detail": "Task is not queued."}, status=status.HTTP_404_NOT_FOUND)


class BackupViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Backup.objects.all()
    serializer_class = BackupSerializer

    def create(self, request, *args, **kwargs):
        from ostium.operations.backup import create_backup

        password = request.data.get("password") or os.environ.get("OSTIUM_BACKUP_PASSWORD", "")
        if not password:
            return Response({"detail": "A backup password is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            backup = create_backup(password=password, note=request.data.get("note", ""), actor=_actor(request))
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit(action="backup.created", request=request, target=backup.filename)
        return Response(BackupSerializer(backup).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        from ostium.operations.backup import delete_backup

        delete_backup(self.get_object(), actor=_actor(request))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        from ostium.operations.backup import restore_backup

        backup = self.get_object()
        password = request.data.get("password") or os.environ.get("OSTIUM_BACKUP_PASSWORD", "")
        if not password:
            return Response({"detail": "A backup password is required."}, status=status.HTTP_400_BAD_REQUEST)
        actor = _actor(request)
        try:
            restore_backup(backup, password=password, actor=actor)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        # The restored database may not contain the caller, so record the event
        # without an actor FK and keep the username in the detail payload.
        AuditEvent.objects.create(
            action="backup.restored",
            target=backup.filename[:200],
            detail={"requested_by": actor.get_username() if actor is not None else ""},
        )
        return Response({"detail": "Backup restored. Restart the worker to apply the restored database."})


class AlertViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Alert.objects.all()
    serializer_class = AlertSerializer
    pagination_class = None

    @action(detail=True, methods=["post"])
    def ack(self, request, pk=None):
        alert = acknowledge_alert(self.get_object())
        record_audit(action="alert.acknowledged", request=request, target=alert.code)
        return Response(AlertSerializer(alert).data)


class AuditViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = AuditEventSerializer

    def get_queryset(self):
        queryset = AuditEvent.objects.select_related("actor")
        action_name = self.request.query_params.get("action")
        actor = self.request.query_params.get("actor")
        if action_name:
            queryset = queryset.filter(action__startswith=action_name)
        if actor:
            queryset = queryset.filter(actor__username=actor)
        return queryset


class SettingsView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        from django.conf import settings as django_settings

        from ostium.operations.runtime_settings import MASKED_SECRET, SECRET_SETTINGS

        payload = {}
        for key in django_settings.CONSTANCE_CONFIG:
            value = getattr(runtime_config, key)
            payload[key] = MASKED_SECRET if key in SECRET_SETTINGS and value else value
        return Response(payload)

    @extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    def patch(self, request):
        from django.conf import settings as django_settings

        from ostium.operations.runtime_settings import (
            MASKED_SECRET,
            SECRET_SETTINGS,
            SettingValidationError,
            coerce_setting,
        )

        payload = request.data
        if not isinstance(payload, dict):
            return Response({"detail": "Expected a JSON object."}, status=status.HTTP_400_BAD_REQUEST)
        unknown = sorted(set(payload) - set(django_settings.CONSTANCE_CONFIG))
        if unknown:
            return Response(
                {"detail": f"Unknown setting(s): {', '.join(unknown)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        coerced = {}
        for key, value in payload.items():
            if key in SECRET_SETTINGS and value == MASKED_SECRET:
                continue
            try:
                coerced[key] = coerce_setting(key, value)
            except SettingValidationError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        for key, value in coerced.items():
            setattr(runtime_config, key, value)
        updated = list(coerced)
        if updated:
            mark_dirty()
            record_audit(action="settings.updated", request=request, detail={"keys": updated})
        return Response({"updated": updated})


class SchemaViewMixin:
    permission_classes = [IsAdminUser]


__all__ = [
    "AlertViewSet",
    "AuditViewSet",
    "BackupViewSet",
    "CertificateViewSet",
    "ConnectionDetailView",
    "ConnectionsView",
    "InboundViewSet",
    "JobViewSet",
    "SettingsView",
    "StatsOverviewView",
    "StatsTrafficView",
    "UserViewSet",
]
