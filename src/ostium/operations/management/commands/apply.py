"""Request a configuration apply."""

from django.core.management.base import BaseCommand

from ostium.operations.models import RuntimeState
from ostium.proxy.services import mark_dirty


class Command(BaseCommand):
    help = "Bump the desired revision so the worker regenerates configuration."

    def handle(self, *args, **options):
        revision = mark_dirty()
        state = RuntimeState.load()
        self.stdout.write(self.style.SUCCESS(f"Requested apply; desired revision is {revision}."))
        if state.worker_alive:
            self.stdout.write("The worker will pick this up within one second.")
        else:
            self.stdout.write(self.style.WARNING("The worker heartbeat is stale; start ostium-worker.service."))
