"""Inbound administration."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from ostium.certificates.models import Certificate
from ostium.proxy.models import Inbound
from ostium.proxy.services import initialize_inbounds


class Command(BaseCommand):
    help = "Inspect and change protocol inbounds."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="subcommand", required=True)
        sub.add_parser("list", help="List inbounds.")
        init = sub.add_parser("init", help="Create missing inbound records.")
        init.add_argument("--enable", default="vless", help="Comma-separated kinds to enable.")

        enable = sub.add_parser("enable", help="Enable an inbound.")
        enable.add_argument("kind", choices=Inbound.Kind.values)
        enable.add_argument("--cert", default="", help="Certificate domain.")
        disable = sub.add_parser("disable", help="Disable an inbound.")
        disable.add_argument("kind", choices=Inbound.Kind.values)
        rotate = sub.add_parser("rotate-keys", help="Rotate protocol secrets.")
        rotate.add_argument("kind", choices=Inbound.Kind.values)
        port = sub.add_parser("set-port", help="Change the listening port.")
        port.add_argument("kind", choices=Inbound.Kind.values)
        port.add_argument("port", type=int)

    def handle(self, *args, **options):
        getattr(self, f"_{options['subcommand'].replace('-', '_')}")(options)

    def _list(self, options):
        for inbound in Inbound.objects.all():
            cert = inbound.certificate.domain if inbound.certificate else "-"
            errors = "; ".join(inbound.validation_errors()) or "ready"
            self.stdout.write(
                f"{inbound.kind:14} {'enabled' if inbound.enabled else 'disabled':9} "
                f"{inbound.listen}:{inbound.port:<6} cert={cert:24} {errors}"
            )

    def _init(self, options):
        enable = tuple(item.strip() for item in options["enable"].split(",") if item.strip())
        records = initialize_inbounds(enable=enable)
        self.stdout.write(self.style.SUCCESS(f"Initialized {len(records)} inbound record(s)."))

    def _enable(self, options):
        inbound = Inbound.objects.filter(kind=options["kind"]).first()
        if inbound is None:
            raise CommandError("Run 'ostium inbound init' first.")
        if inbound.needs_certificate:
            if not options["cert"]:
                raise CommandError("This protocol requires --cert <domain>.")
            certificate = Certificate.objects.filter(domain=options["cert"]).first()
            if certificate is None:
                raise CommandError(f"Certificate {options['cert']!r} not found.")
            if not certificate.is_ready:
                raise CommandError("Certificate is not ready.")
            inbound.certificate = certificate
        inbound.enabled = True
        try:
            inbound.full_clean()
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        inbound.save()
        self.stdout.write(self.style.SUCCESS(f"Enabled {inbound.kind} on port {inbound.port}."))

    def _disable(self, options):
        inbound = Inbound.objects.filter(kind=options["kind"]).first()
        if inbound is None:
            raise CommandError("Inbound does not exist.")
        inbound.enabled = False
        inbound.save(update_fields=["enabled", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"Disabled {inbound.kind}."))

    def _rotate_keys(self, options):
        inbound = Inbound.objects.filter(kind=options["kind"]).first()
        if inbound is None:
            raise CommandError("Inbound does not exist.")
        inbound.rotate_keys()
        self.stdout.write(self.style.SUCCESS(f"Rotated keys for {inbound.kind}."))

    def _set_port(self, options):
        inbound = Inbound.objects.filter(kind=options["kind"]).first()
        if inbound is None:
            raise CommandError("Inbound does not exist.")
        if not 1 <= options["port"] <= 65535:
            raise CommandError("Port must be between 1 and 65535.")
        inbound.port = options["port"]
        try:
            inbound.full_clean()
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        inbound.save(update_fields=["port", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"{inbound.kind} now listens on {inbound.port}."))
