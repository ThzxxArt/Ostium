"""Operations app configuration."""

from django.apps import AppConfig


class OperationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ostium.operations"
    verbose_name = "运维"
