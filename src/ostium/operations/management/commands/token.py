"""Scoped API key administration."""

from __future__ import annotations

import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ostium.accounts.models import ApiKey


class Command(BaseCommand):
    help = "Create, list and revoke API keys."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="subcommand", required=True)
        create = sub.add_parser("create", help="Create an API key; the secret is shown once.")
        create.add_argument("name")
        create.add_argument("--scope", choices=ApiKey.Scope.values, default=ApiKey.Scope.READ)
        create.add_argument("--expires", type=int, default=0, help="Days until expiry; 0 means never.")
        create.add_argument("--json", action="store_true")

        listing = sub.add_parser("list")
        listing.add_argument("--json", action="store_true")

        revoke = sub.add_parser("revoke")
        revoke.add_argument("prefix")

    def handle(self, *args, **options):
        getattr(self, f"_{options['subcommand']}")(options)

    def _create(self, options):
        expiry = timezone.now() + timedelta(days=options["expires"]) if options["expires"] else None
        key, plaintext = ApiKey.objects.create_key(
            name=options["name"],
            scope=options["scope"],
            expiry_date=expiry,
        )
        payload = {"name": key.name, "prefix": key.prefix, "scope": key.scope, "key": plaintext}
        if options["json"]:
            self.stdout.write(json.dumps(payload, indent=2))
        else:
            self.stdout.write(self.style.SUCCESS(f"Created API key {key.name} ({key.scope})."))
            self.stdout.write(plaintext)
            self.stdout.write("Store it now; it cannot be shown again.")

    def _list(self, options):
        keys = ApiKey.objects.all()
        if options["json"]:
            self.stdout.write(
                json.dumps(
                    [
                        {
                            "name": key.name,
                            "prefix": key.prefix,
                            "scope": key.scope,
                            "created": key.created,
                            "expiry_date": key.expiry_date,
                            "revoked": key.revoked,
                            "last_used_at": key.last_used_at,
                        }
                        for key in keys
                    ],
                    indent=2,
                    default=str,
                )
            )
            return
        for key in keys:
            state = "revoked" if key.revoked else "active"
            self.stdout.write(f"{key.prefix:10} {key.name:30} {key.scope:8} {state:8} {key.created:%Y-%m-%d}")

    def _revoke(self, options):
        updated = ApiKey.objects.filter(prefix=options["prefix"]).update(revoked=True)
        if not updated:
            raise CommandError("No key with that prefix.")
        self.stdout.write(self.style.SUCCESS(f"Revoked {updated} key(s)."))
