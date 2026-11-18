"""Certificate administration."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ostium.certificates.models import Certificate
from ostium.certificates.services import (
    delete_certificate,
    generate_self_signed,
    import_certificate,
    sync_directory,
)


class Command(BaseCommand):
    help = "Import, synchronize and inspect TLS certificates."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="subcommand", required=True)
        sub.add_parser("list", help="List certificates.")

        imp = sub.add_parser("import", help="Import a certificate and key.")
        imp.add_argument("--domain", required=True)
        imp.add_argument("--cert", required=True, help="Path to fullchain PEM.")
        imp.add_argument("--key", required=True, help="Path to private key PEM.")
        imp.add_argument("--auto-renew", action="store_true")

        sync = sub.add_parser("sync", help="Import certbot live directories.")
        sync.add_argument("--dir", default="/etc/letsencrypt/live")

        self_signed = sub.add_parser("self-signed", help="Generate a self-signed certificate.")
        self_signed.add_argument("--domain", required=True)
        self_signed.add_argument("--days", type=int, default=365)

        delete = sub.add_parser("delete", help="Delete an unused certificate.")
        delete.add_argument("domain")

    def handle(self, *args, **options):
        getattr(self, f"_{options['subcommand'].replace('-', '_')}")(options)

    def _list(self, options):
        for cert in Certificate.objects.all():
            self.stdout.write(
                f"{cert.domain:40} {cert.status:10} {cert.days_remaining:4}d  "
                f"{cert.get_source_display():12} {'managed' if cert.auto_renew else 'manual'}"
            )

    def _import(self, options):
        cert_file = Path(options["cert"])
        key_file = Path(options["key"])
        if not cert_file.is_file() or not key_file.is_file():
            raise CommandError("Certificate or key file not found.")
        try:
            certificate = import_certificate(
                domain=options["domain"],
                cert_pem=cert_file.read_text(encoding="utf-8"),
                key_pem=key_file.read_text(encoding="utf-8"),
                auto_renew=options["auto_renew"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(f"Imported {certificate.domain} (expires {certificate.expires_at:%Y-%m-%d}).")
        )

    def _sync(self, options):
        try:
            certificates = sync_directory(Path(options["dir"]))
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        for cert in certificates:
            self.stdout.write(self.style.SUCCESS(f"Synced {cert.domain} (expires {cert.expires_at:%Y-%m-%d})."))

    def _self_signed(self, options):
        try:
            certificate = generate_self_signed(options["domain"], days=options["days"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Generated self-signed certificate for {certificate.domain}."))
        self.stdout.write(
            "Clients must pin or trust this certificate; subscriptions include pinSHA256 where supported."
        )

    def _delete(self, options):
        certificate = Certificate.objects.filter(domain=options["domain"]).first()
        if certificate is None:
            raise CommandError("Certificate not found.")
        try:
            delete_certificate(certificate)
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Certificate deleted."))
