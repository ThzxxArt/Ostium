"""API URL routing."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from ostium.operations import health

from .views import (
    AlertViewSet,
    AuditViewSet,
    BackupViewSet,
    CertificateViewSet,
    ConnectionDetailView,
    ConnectionsView,
    InboundViewSet,
    JobViewSet,
    SettingsView,
    StatsOverviewView,
    StatsTrafficView,
    UserViewSet,
)

router = DefaultRouter(trailing_slash=False)
router.register("users", UserViewSet, basename="user")
router.register("inbounds", InboundViewSet, basename="inbound")
router.register("certificates", CertificateViewSet, basename="certificate")
router.register("jobs", JobViewSet, basename="job")
router.register("backups", BackupViewSet, basename="backup")
router.register("alerts", AlertViewSet, basename="alert")
router.register("audit", AuditViewSet, basename="audit")

urlpatterns = [
    path("healthz", health.healthz, name="api-healthz"),
    path("readyz", health.readyz, name="api-readyz"),
    path("metrics", health.metrics, name="api-metrics"),
    path("stats/overview", StatsOverviewView.as_view(), name="stats-overview"),
    path("stats/traffic", StatsTrafficView.as_view(), name="stats-traffic"),
    path("connections", ConnectionsView.as_view(), name="connections"),
    path("connections/<str:connection_id>", ConnectionDetailView.as_view(), name="connection-detail"),
    path("settings", SettingsView.as_view(), name="settings"),
    path("", include(router.urls)),
]
