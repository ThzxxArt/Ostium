"""Export a redacted diagnostic bundle."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ostium.operations.diagnostics import build_diagnostics


class Command(BaseCommand):
    help = "Write a redacted tar.gz diagnostic bundle."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=str(Path(tempfile.gettempdir()) / "ostium-diagnostics.tar.gz"),
        )

    def handle(self, *args, **options):
        path = Path(options["output"])
        try:
            payload = build_diagnostics()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            os.chmod(path, 0o600)
        except OSError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Wrote {path} ({len(payload)} bytes, mode 0600)."))
