"""Inspect generated subscription profiles for one user."""

from __future__ import annotations

import json
from dataclasses import asdict

from django.core.management.base import BaseCommand, CommandError

from ostium.proxy.models import ProxyUser
from ostium.subscriptions.checks import FAIL, PASS, SKIP, check_subscription
from ostium.subscriptions.services import public_host


class Command(BaseCommand):
    help = "Check generated subscription profiles for one proxy user."

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(dest="action", required=True)
        check = subparsers.add_parser("check", help="Run profile compatibility checks.")
        check.add_argument("--user", required=True, help="Proxy user name.")
        check.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
        check.add_argument(
            "--no-binaries",
            action="store_true",
            help="Only run structural checks; do not invoke mihomo/sing-box/xray.",
        )

    def handle(self, *args, **options):
        user = ProxyUser.objects.filter(name=options["user"]).first()
        if user is None:
            raise CommandError(f"Unknown proxy user: {options['user']}")

        results = check_subscription(
            user,
            host=public_host(None),
            run_binaries=not options["no_binaries"],
        )
        if options["json"]:
            self.stdout.write(
                json.dumps(
                    {
                        "user": user.name,
                        "ok": all(result.status != FAIL for result in results),
                        "checks": [asdict(result) for result in results],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            labels = {PASS: "PASS", FAIL: "FAIL", SKIP: "SKIP"}
            self.stdout.write(f"Subscription check: {user.name}")
            for result in results:
                self.stdout.write(f"  [{labels[result.status]:4}] {result.label}: {result.detail}")
            self.stdout.write("Result: " + ("PASS" if all(result.status != FAIL for result in results) else "FAIL"))
        if any(result.status == FAIL for result in results):
            raise CommandError("Subscription compatibility check failed.")
