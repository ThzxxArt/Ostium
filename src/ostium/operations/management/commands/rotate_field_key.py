"""Rotate the AES-GCM field key.

This is an offline operation: stop the web and worker first, run the command
with the new key, update ``OSTIUM_FIELD_KEY`` in the environment file, then
start the services again.
"""

from __future__ import annotations

import base64

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ostium.accounts.crypto import decrypt_text, encrypt_text
from ostium.proxy.models import Inbound, ProxyUser


class Command(BaseCommand):
    help = "Re-encrypt all encrypted fields with a new 32-byte base64 field key."

    def add_arguments(self, parser):
        parser.add_argument("--new-key", required=True)
        parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    def handle(self, *args, **options):
        new_key = options["new_key"].strip()
        try:
            if len(base64.b64decode(new_key)) != 32:
                raise ValueError
        except Exception as exc:
            raise CommandError("--new-key must be base64-encoded 32 bytes.") from exc
        if not options["yes"]:
            self.stdout.write(self.style.WARNING("Stop ostium-web and ostium-worker before continuing."))
            answer = input("Type ROTATE to re-encrypt every credential: ")
            if answer != "ROTATE":
                raise CommandError("Aborted.")

        from ostium.accounts.crypto import decrypt_json, encrypt_json

        old_key = settings.OSTIUM_FIELD_KEY
        users = list(ProxyUser.objects.all())
        inbounds = list(Inbound.objects.all())
        with transaction.atomic():
            for user in users:
                settings.OSTIUM_FIELD_KEY = old_key
                password = decrypt_text(user, "password_enc", user.password_enc)
                ss_password = decrypt_text(user, "ss_password_enc", user.ss_password_enc)
                token = decrypt_text(user, "subscription_token_enc", user.subscription_token_enc)
                settings.OSTIUM_FIELD_KEY = new_key
                ProxyUser.objects.filter(pk=user.pk).update(
                    password_enc=encrypt_text(user, "password_enc", password),
                    ss_password_enc=encrypt_text(user, "ss_password_enc", ss_password),
                    subscription_token_enc=encrypt_text(user, "subscription_token_enc", token),
                )
            for inbound in inbounds:
                settings.OSTIUM_FIELD_KEY = old_key
                params = decrypt_json(inbound, "params_enc", inbound.params_enc)
                settings.OSTIUM_FIELD_KEY = new_key
                Inbound.objects.filter(pk=inbound.pk).update(params_enc=encrypt_json(inbound, "params_enc", params))
        settings.OSTIUM_FIELD_KEY = new_key
        self.stdout.write(self.style.SUCCESS("Re-encrypted all fields."))
        self.stdout.write("Update OSTIUM_FIELD_KEY in /etc/ostium/ostium.env, then restart the services.")
