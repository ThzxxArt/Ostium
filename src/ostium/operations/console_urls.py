"""Aurora console URL routing."""

from django.urls import path

from . import console_views

app_name = "console"

urlpatterns = [
    path("", console_views.dashboard, name="dashboard"),
    path("users/", console_views.users, name="users"),
    path("users/<uuid:user_id>/", console_views.user_detail, name="user_detail"),
    path("inbounds/", console_views.inbounds, name="inbounds"),
    path("subscriptions/", console_views.subscriptions, name="subscriptions"),
    path("connections/", console_views.connections, name="connections"),
    path("certificates/", console_views.certificates, name="certificates"),
    path("logs/", console_views.logs, name="logs"),
    path("jobs/", console_views.jobs, name="jobs"),
    path("system/", console_views.system, name="system"),
    path("settings/", console_views.settings_view, name="settings"),
    path("audit/", console_views.audit, name="audit"),
]
