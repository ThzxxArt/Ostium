"""Operational doctor."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from ostium.operations.doctor import doctor_summary, run_doctor


class Command(BaseCommand):
    help = "Run non-destructive health checks."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        checks = run_doctor()
        summary = doctor_summary(checks)
        if options["json"]:
            self.stdout.write(json.dumps({"summary": summary, "checks": checks}, indent=2))
        else:
            for check in checks:
                marker = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}[check["status"]]
                self.stdout.write(f"[{marker}] {check['name']}: {check['detail']}")
                if check["fix"]:
                    self.stdout.write(f"       fix: {check['fix']}")
            self.stdout.write(f"\n{summary['pass']} passed, {summary['warn']} warnings, {summary['fail']} failures")
        if summary["fail"]:
            raise SystemExit(1)
