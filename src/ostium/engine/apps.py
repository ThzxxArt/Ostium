"""Engine app configuration."""

from django.apps import AppConfig


class EngineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ostium.engine"
    verbose_name = "Engine"
