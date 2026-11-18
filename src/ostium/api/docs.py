"""OpenAPI schema and documentation views."""

from __future__ import annotations

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny


class PublicSchemaView(SpectacularAPIView):
    """The schema contains no secrets and is useful to API clients."""

    permission_classes = [AllowAny]


class StaffDocsView(SpectacularSwaggerView):
    permission_classes = [AllowAny]
