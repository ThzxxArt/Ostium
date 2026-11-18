"""API-key authentication and scope enforcement."""

from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS
from rest_framework_api_key.permissions import BaseHasAPIKey

from ostium.accounts.models import ApiKey


class HasOstiumAPIKey(BaseHasAPIKey):
    model = ApiKey
    message = "A valid Ostium API key is required."

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        key = self.get_key(request)
        if not key:
            return False
        try:
            api_key = ApiKey.objects.get_from_key(key)
        except ApiKey.DoesNotExist:
            return False
        if request.method not in SAFE_METHODS and not api_key.can_write:
            self.message = "This API key is read-only."
            return False
        ip = request.META.get("REMOTE_ADDR")
        api_key.touch(ip)
        request.api_key = api_key
        return True


__all__ = ["HasOstiumAPIKey"]
