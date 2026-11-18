"""Encrypted backup creation and restore."""

from __future__ import annotations

import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ostium.operations.backup import create_backup, restore_file
from ostium.operations.models import Backup


class Command(BaseCommand):
    help = "Create, list and restore encrypted Ostium backups."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="subcommand", required=True)
        create = sub.add_parser("create", help="Create a backup.")
        create.add_argument("--password", default=os.environ.get("OSTIUM_BACKUP_PASSWORD", ""))
        create.add_argument("--note", default="")
        sub.add_parser("list", help="List backups.")
        restore = sub.add_parser("restore", help="Restore a backup file (offline recommended).")
        restore.add_argument("path")
        restore.add_argument("--password", default=os.environ.get("OSTIUM_BACKUP_PASSWORD", ""))

    def handle(self, *args, **options):
        getattr(self, f"_{options['subcommand']}")(options)

    def _create(self, options):
        if not options["password"]:
            raise CommandError("Provide --password or set OSTIUM_BACKUP_PASSWORD.")
        try:
            backup = create_backup(password=options["password"], note=options["note"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Created {backup.filename} ({backup.size} bytes)."))

    def _list(self, options):
        for backup in Backup.objects.all():
            self.stdout.write(
                f"{backup.filename:46} {backup.size:12}  {backup.created_at:%Y-%m-%d %H:%M}  {backup.note}"
            )

    def _restore(self, options):
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError(f"Backup file not found: {path}")
        if not options["password"]:
            raise CommandError("Provide --password or set OSTIUM_BACKUP_PASSWORD.")
        self.stdout.write(self.style.WARNING("Restoring replaces the current database and certificate files."))
        try:
            restore_file(path, password=options["password"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS("Restore complete. Restart ostium-worker to apply the restored configuration.")
        )
