"""Subscription URL routing."""

from django.urls import re_path

from .views import subscription

app_name = "subscriptions"

urlpatterns = [
    re_path(
        r"^(?P<token>[A-Za-z0-9_-]{20,128})(?:/(?P<path_target>v2ray|clash|singbox))?/?$",
        subscription,
        name="subscription",
    ),
]
