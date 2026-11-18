"""User administration."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ostium.proxy.models import ProxyUser, validate_user_name
from ostium.proxy.services import create_proxy_user, parse_size
from ostium.subscriptions.services import masked_token, subscription_links


def _datetime(value: str | None):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CommandError(f"Invalid ISO-8601 datetime: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _find(name: str) -> ProxyUser:
    user = ProxyUser.objects.filter(name=name).first()
    if user is None:
        raise CommandError(f"User {name!r} does not exist.")
    return user


class Command(BaseCommand):
    help = "Create, inspect and manage proxy users."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="subcommand", required=True)

        add = sub.add_parser("add", help="Create a user.")
        add.add_argument("name")
        add.add_argument("--quota", default="0", help="e.g. 100G; 0 means unlimited.")
        add.add_argument("--cycle", choices=ProxyUser.QuotaCycle.values, default=ProxyUser.QuotaCycle.TOTAL)
        add.add_argument("--expires", default=None)
        add.add_argument("--note", default="")
        add.add_argument("--disabled", action="store_true")
        add.add_argument("--reveal", action="store_true", help="Print the full subscription token.")
        add.add_argument("--json", action="store_true")

        listing = sub.add_parser("list", help="List users.")
        listing.add_argument("--json", action="store_true")

        show = sub.add_parser("show", help="Show one user.")
        show.add_argument("name")
        show.add_argument("--json", action="store_true")

        for name, help_text in (
            ("disable", "Disable a user."),
            ("enable", "Enable a user."),
            ("delete", "Delete a user."),
            ("reset-usage", "Reset usage counters."),
        ):
            command = sub.add_parser(name, help=help_text)
            command.add_argument("name")

        rotate = sub.add_parser("rotate", help="Rotate credentials or the subscription token.")
        rotate.add_argument("name")
        group = rotate.add_mutually_exclusive_group()
        group.add_argument("--credentials", action="store_true")
        group.add_argument("--subscription", action="store_true")
        rotate.add_argument("--reveal", action="store_true", help="Print the new full subscription token.")

        subscription = sub.add_parser("subscription", help="Show subscription URLs.")
        subscription.add_argument("name")
        subscription.add_argument("--reveal", action="store_true")
        subscription.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        sub = options["subcommand"]
        getattr(self, f"_{sub.replace('-', '_')}")(options)

    def _add(self, options):
        try:
            name = validate_user_name(options["name"])
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        try:
            quota = parse_size(options["quota"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        expires = _datetime(options["expires"])
        if expires is not None and expires <= timezone.now():
            raise CommandError("Expiry must be in the future.")
        if ProxyUser.objects.filter(name=name).exists():
            raise CommandError("A user with this name already exists.")
        user, token = create_proxy_user(
            name,
            quota_bytes=quota,
            quota_cycle=options["cycle"],
            expires_at=expires,
            note=options["note"],
            enabled=not options["disabled"],
        )
        revealed = bool(options["reveal"])
        payload = {
            "id": str(user.id),
            "name": user.name,
            "uuid": str(user.uuid),
            "token": token if revealed else masked_token(user),
            "revealed": revealed,
        }
        if options["json"]:
            self.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        self.stdout.write(self.style.SUCCESS(f"Created user {user.name}."))
        if revealed:
            self.stdout.write(f"  subscription token: {token}")
        else:
            self.stdout.write(f"  subscription token: {payload['token']} (masked)")
            self.stdout.write("  run 'ostium user subscription <name> --reveal' to print the full URLs.")
        self.stdout.write("  enable an inbound, then import the subscription in your client.")

    def _list(self, options):
        users = ProxyUser.objects.all()
        if options["json"]:
            self.stdout.write(
                json.dumps(
                    [
                        {
                            "id": str(user.id),
                            "name": user.name,
                            "status": user.status,
                            "used_bytes": user.used_bytes,
                            "quota_bytes": user.quota_bytes,
                            "quota_percent": user.quota_percent,
                            "expires_at": user.expires_at,
                            "last_seen_at": user.last_seen_at,
                        }
                        for user in users
                    ],
                    indent=2,
                    default=str,
                )
            )
            return
        if not users:
            self.stdout.write("No users.")
            return
        self.stdout.write(f"{'NAME':24} {'STATUS':16} {'USED':>12} {'QUOTA':>12}  EXPIRES")
        for user in users:
            quota = f"{user.quota_bytes}" if user.quota_bytes else "unlimited"
            expires = user.expires_at.strftime("%Y-%m-%d") if user.expires_at else "never"
            self.stdout.write(f"{user.name:24} {user.status:16} {user.used_bytes:12} {quota:>12}  {expires}")

    def _show(self, options):
        user = _find(options["name"])
        payload = {
            "id": str(user.id),
            "name": user.name,
            "enabled": user.enabled,
            "status": user.status,
            "uuid": str(user.uuid),
            "used_bytes": user.used_bytes,
            "quota_bytes": user.quota_bytes,
            "quota_cycle": user.quota_cycle,
            "expires_at": user.expires_at,
            "last_seen_at": user.last_seen_at,
            "note": user.note,
        }
        if options["json"]:
            self.stdout.write(json.dumps(payload, indent=2, default=str, ensure_ascii=False))
        else:
            for key, value in payload.items():
                self.stdout.write(f"{key:16} {value}")

    def _disable(self, options):
        user = _find(options["name"])
        user.disable()
        self.stdout.write(self.style.SUCCESS(f"Disabled {user.name}."))

    def _enable(self, options):
        user = _find(options["name"])
        user.enable()
        self.stdout.write(self.style.SUCCESS(f"Enabled {user.name}."))

    def _delete(self, options):
        user = _find(options["name"])
        user.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {user.name}."))

    def _reset_usage(self, options):
        user = _find(options["name"])
        user.reset_usage()
        self.stdout.write(self.style.SUCCESS(f"Reset usage for {user.name}."))

    def _rotate(self, options):
        user = _find(options["name"])
        if options["subscription"]:
            token = user.rotate_subscription_token()
            self.stdout.write(self.style.SUCCESS(f"Rotated subscription token for {user.name}."))
            if options["reveal"]:
                self.stdout.write(token)
            else:
                self.stdout.write(f"{masked_token(user)} (masked)")
                self.stdout.write("Use --reveal to print the new token.")
        else:
            user.rotate_credentials()
            self.stdout.write(self.style.SUCCESS(f"Rotated credentials for {user.name}."))
            self.stdout.write("Clients must re-import their subscription.")

    def _subscription(self, options):
        user = _find(options["name"])
        if options["reveal"]:
            links = subscription_links(user)
            payload = {"token": user.reveal_subscription_token(), "links": links}
        else:
            payload = {"token": masked_token(user), "links": []}
        if options["json"]:
            self.stdout.write(json.dumps(payload, indent=2))
            return
        self.stdout.write(f"token: {payload['token']}")
        for link in links if options["reveal"] else []:
            self.stdout.write(f"  {link['label']}: {link['url']}")
        if not options["reveal"]:
            self.stdout.write("Use --reveal to print the full URLs (recorded as a sensitive terminal action).")
