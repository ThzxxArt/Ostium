"""Run the production WSGI server."""

from __future__ import annotations

import os
import shutil

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Start Gunicorn in the foreground (127.0.0.1:8000 by default)."

    def add_arguments(self, parser):
        parser.add_argument("--bind", default="127.0.0.1:8000")
        parser.add_argument("--workers", default=os.environ.get("OSTIUM_WEB_WORKERS", "2"))
        parser.add_argument("--timeout", default="60")

    def handle(self, *args, **options):
        gunicorn = shutil.which("gunicorn")
        if not gunicorn:
            raise CommandError("gunicorn is not installed in this environment.")
        env = os.environ.copy()
        env.setdefault("DJANGO_SETTINGS_MODULE", "ostium.config.settings.prod")
        argv = [
            gunicorn,
            "ostium.config.wsgi:application",
            "--bind",
            options["bind"],
            "--workers",
            str(options["workers"]),
            "--timeout",
            str(options["timeout"]),
            "--access-logfile",
            "-",
            "--error-logfile",
            "-",
            "--forwarded-allow-ips",
            "127.0.0.1",
        ]
        self.stdout.write(f"starting: {' '.join(argv)}")
        os.execvpe(gunicorn, argv, env)
