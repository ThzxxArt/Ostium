"""Initialize an Ostium installation."""

from __future__ import annotations

import secrets

from constance import config
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ostium.accounts.models import AdminProfile
from ostium.proxy.services import initialize_inbounds, mark_dirty


class Command(BaseCommand):
    help = "Create the administrator, initialize inbounds and seed runtime settings."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--password", default=None, help="Initial password; generated when omitted.")
        parser.add_argument("--email", default="")
        parser.add_argument("--domain", default="", help="Public hostname, e.g. vpn.example.com.")
        parser.add_argument("--no-inbounds", action="store_true")
        parser.add_argument("--enable", default="vless", help="Comma-separated inbound kinds to enable initially.")

    def handle(self, *args, **options):
        username = options["username"].strip()
        if not username:
            raise CommandError("Username must not be blank.")
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            raise CommandError(f"User {username!r} already exists; refusing to overwrite.")

        password = options["password"] or secrets.token_urlsafe(18)
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc

        domain = options["domain"].strip().rstrip("/")
        for prefix in ("https://", "http://"):
            if domain.startswith(prefix):
                domain = domain.removeprefix(prefix)
                break
        with transaction.atomic():
            user = User.objects.create_superuser(username=username, email=options["email"], password=password)
            AdminProfile.objects.update_or_create(
                user=user,
                defaults={"must_change_password": True, "totp_required": True},
            )
            if not options["no_inbounds"]:
                enable = tuple(item.strip() for item in options["enable"].split(",") if item.strip())
                initialize_inbounds(enable=enable)
            if domain:
                config.public_host = domain
                config.public_base_url = f"https://{domain}"
                config.server_name = domain
            mark_dirty()

        self.stdout.write(self.style.SUCCESS("Ostium initialized."))
        self.stdout.write(f"  username: {username}")
        if not options["password"]:
            self.stdout.write(self.style.WARNING(f"  initial password: {password}"))
        if domain:
            self.stdout.write(f"  public host: {domain}")
            self.stdout.write(
                self.style.WARNING(
                    "  Enable TOTP before exposing the console: http://127.0.0.1:8000/accounts/totp/setup/"
                )
            )
        self.stdout.write("  next: ostium migrate && ostium collectstatic && ostium web")
        if not options["no_inbounds"]:
            self.stdout.write("  enabled inbounds: " + ", ".join(options["enable"].split(",")))
            if "hysteria2" in options["enable"] or "trojan" in options["enable"]:
                self.stdout.write("  note: certificate-based inbounds need a certificate before they can start.")
