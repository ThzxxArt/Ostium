"""Run the data-plane worker."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from ostium.engine.worker import run_worker


class Command(BaseCommand):
    help = "Supervise sing-box and apply database-driven configuration."

    def handle(self, *args, **options):
        code = run_worker()
        if code:
            raise SystemExit(code)
