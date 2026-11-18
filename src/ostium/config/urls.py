"""Root URL configuration."""

from __future__ import annotations

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.urls import include, path
from health_check.views import HealthCheckView

from ostium.api.docs import PublicSchemaView, StaffDocsView
from ostium.api.errors import api_not_found
from ostium.operations import health


class OstiumHealthCheckView(HealthCheckView):
    checks = [
        "health_check.checks.Database",
        "health_check.checks.Cache",
        "health_check.checks.Storage",
    ]


urlpatterns = [
    path("api/schema", PublicSchemaView.as_view(), name="schema"),
    path("api/docs", staff_member_required(StaffDocsView.as_view(url_name="schema")), name="docs"),
    path("admin/", admin.site.urls),
    path("accounts/", include("ostium.accounts.urls")),
    path("sub/", include("ostium.subscriptions.urls")),
    path("api/v1/", include("ostium.api.urls")),
    path("api/v1/<path:unknown>", api_not_found),
    path("healthz", health.healthz, name="healthz"),
    path("readyz", health.readyz, name="readyz"),
    path("metrics", health.metrics, name="metrics"),
    path("health/", OstiumHealthCheckView.as_view(), name="health"),
    path("", include("ostium.operations.console_urls")),
]
