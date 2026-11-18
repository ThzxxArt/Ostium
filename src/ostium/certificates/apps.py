"""Certificates app configuration."""

from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save


class CertificatesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ostium.certificates"
    verbose_name = "Certificates"

    def ready(self) -> None:
        from auditlog.registry import auditlog

        from .models import Certificate

        auditlog.register(Certificate)

        def bump(sender, instance, **kwargs):
            from django.db.utils import OperationalError, ProgrammingError

            from ostium.proxy.services import mark_dirty

            try:
                mark_dirty()
            except OperationalError, ProgrammingError:
                pass

        post_save.connect(bump, sender=Certificate, dispatch_uid="ostium.certificate_changed", weak=False)
        post_delete.connect(bump, sender=Certificate, dispatch_uid="ostium.certificate_deleted", weak=False)
