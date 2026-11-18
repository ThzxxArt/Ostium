"""Show a concise installation status."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from ostium.certificates.models import Certificate
from ostium.operations.models import RuntimeState
from ostium.proxy.models import Inbound, ProxyUser
from ostium.version import BUILD_COMMIT, BUILD_DATE, __version__


class Command(BaseCommand):
    help = "Show runtime, user, inbound and certificate status."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        state = RuntimeState.load()
        payload = {
            "version": __version__,
            "build_commit": BUILD_COMMIT,
            "build_date": BUILD_DATE,
            "runtime": {
                "desired_revision": state.desired_revision,
                "applied_revision": state.applied_revision,
                "config_sha256": state.config_sha256,
                "singbox_running": state.singbox_running,
                "singbox_pid": state.singbox_pid,
                "worker_alive": state.worker_alive,
                "worker_heartbeat": state.worker_heartbeat,
                "last_error": state.last_error,
            },
            "users": {
                "total": ProxyUser.objects.count(),
                "enabled": ProxyUser.objects.filter(enabled=True).count(),
            },
            "inbounds": [
                {
                    "kind": inbound.kind,
                    "enabled": inbound.enabled,
                    "listen": inbound.listen,
                    "port": inbound.port,
                    "certificate": inbound.certificate.domain if inbound.certificate else None,
                    "errors": inbound.validation_errors(),
                }
                for inbound in Inbound.objects.all()
            ],
            "certificates": [
                {"domain": cert.domain, "status": cert.status, "days_remaining": cert.days_remaining}
                for cert in Certificate.objects.all()
            ],
        }
        if options["json"]:
            self.stdout.write(json.dumps(payload, indent=2, default=str, ensure_ascii=False))
            return
        self.stdout.write(f"Ostium Server {__version__} ({BUILD_COMMIT})")
        self.stdout.write(
            f"  worker: {'alive' if state.worker_alive else 'DOWN'}  "
            f"sing-box: {'running pid ' + str(state.singbox_pid) if state.singbox_running else 'stopped'}"
        )
        self.stdout.write(
            f"  revision: {state.applied_revision}/{state.desired_revision}  sha256: {state.config_sha256 or '-'}"
        )
        if state.last_error:
            self.stdout.write(self.style.ERROR(f"  last error: {state.last_error[:300]}"))
        self.stdout.write(f"  users: {payload['users']['enabled']}/{payload['users']['total']} enabled")
        for inbound in payload["inbounds"]:
            state_label = "on" if inbound["enabled"] else "off"
            errors = f"  errors: {'; '.join(inbound['errors'])}" if inbound["errors"] else ""
            self.stdout.write(f"  {inbound['kind']:14} {state_label:3} {inbound['listen']}:{inbound['port']}{errors}")
        for cert in payload["certificates"]:
            self.stdout.write(f"  cert {cert['domain']:36} {cert['status']:8} {cert['days_remaining']}d")
