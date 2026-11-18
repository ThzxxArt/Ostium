"""Proxy domain models: users, inbounds, traffic history and stats epochs."""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import date, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ostium.accounts.crypto import decrypt_json, decrypt_text, encrypt_json, encrypt_text

TOKEN_BYTES = 32


def validate_user_name(value: str) -> str:
    """Validate a name used as a sing-box user and V2Ray stats key."""

    name = (value or "").strip()
    if not 1 <= len(name) <= 64:
        raise ValidationError(_("User name must be between 1 and 64 characters."))
    if ">" in name or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValidationError(_("User name must not contain '>' or control characters."))
    return name


def generate_subscription_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_subscription_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_password(length: int = 24) -> str:
    return secrets.token_urlsafe(length)


def generate_ss_key(size: int = 16) -> str:
    return base64.b64encode(secrets.token_bytes(size)).decode("ascii")


def generate_reality_keypair() -> tuple[str, str]:
    private = X25519PrivateKey.generate()
    private_raw = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    encode = lambda raw: base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")  # noqa: E731
    return encode(private_raw), encode(public_raw)


def generate_short_id() -> str:
    return secrets.token_hex(4)


class ProxyUser(models.Model):
    class QuotaCycle(models.TextChoices):
        TOTAL = "total", _("Total allowance")
        MONTHLY = "monthly", _("Monthly reset")

    class DisabledReason(models.TextChoices):
        DISABLED = "disabled", _("Disabled by administrator")
        EXPIRED = "expired", _("Expired")
        QUOTA_EXCEEDED = "quota_exceeded", _("Quota exceeded")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=64, unique=True, verbose_name=_("name"))
    enabled = models.BooleanField(default=True, verbose_name=_("enabled"))
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, verbose_name=_("VLESS UUID"))
    password_enc = models.TextField(editable=False)
    ss_password_enc = models.TextField(editable=False)
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name=_("expires at"))
    quota_bytes = models.BigIntegerField(default=0, verbose_name=_("quota (bytes)"), help_text=_("0 means unlimited"))
    quota_cycle = models.CharField(
        max_length=16, choices=QuotaCycle.choices, default=QuotaCycle.TOTAL, verbose_name=_("quota cycle")
    )
    cycle_started_at = models.DateTimeField(null=True, blank=True)
    used_bytes = models.BigIntegerField(default=0, verbose_name=_("used (bytes)"))
    uploaded_bytes = models.BigIntegerField(default=0, verbose_name=_("uploaded (bytes)"))
    downloaded_bytes = models.BigIntegerField(default=0, verbose_name=_("downloaded (bytes)"))
    subscription_token_hash = models.CharField(max_length=64, unique=True, editable=False)
    subscription_token_enc = models.TextField(editable=False)
    note = models.CharField(max_length=500, blank=True, verbose_name=_("note"))
    last_seen_at = models.DateTimeField(null=True, blank=True, verbose_name=_("last seen"))
    disabled_reason = models.CharField(
        max_length=24,
        choices=DisabledReason.choices,
        blank=True,
        default="",
        verbose_name=_("disabled reason"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = _("proxy user")
        verbose_name_plural = _("proxy users")
        indexes = [models.Index(fields=["enabled", "expires_at"])]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        self.name = validate_user_name(self.name)
        if self.quota_bytes < 0:
            raise ValidationError(_("Quota must not be negative."))

    # -- encrypted credentials -------------------------------------------------

    @property
    def password(self) -> str:
        return decrypt_text(self, "password_enc", self.password_enc)

    @property
    def ss_password(self) -> str:
        return decrypt_text(self, "ss_password_enc", self.ss_password_enc)

    def set_password(self, value: str | None = None) -> str:
        value = value or generate_password()
        self.password_enc = encrypt_text(self, "password_enc", value)
        return value

    def set_ss_password(self, value: str | None = None) -> str:
        value = value or generate_ss_key()
        self.ss_password_enc = encrypt_text(self, "ss_password_enc", value)
        return value

    # -- subscription token ----------------------------------------------------

    def set_subscription_token(self, token: str | None = None) -> str:
        token = token or generate_subscription_token()
        self.subscription_token_hash = hash_subscription_token(token)
        self.subscription_token_enc = encrypt_text(self, "subscription_token_enc", token)
        return token

    def reveal_subscription_token(self) -> str:
        return decrypt_text(self, "subscription_token_enc", self.subscription_token_enc)

    # -- lifecycle -------------------------------------------------------------

    def save(self, *args, **kwargs) -> None:
        generating = not self.password_enc or not self.ss_password_enc or not self.subscription_token_hash
        if generating:
            if not self.uuid:
                self.uuid = uuid.uuid4()
            if not self.password_enc:
                self.set_password()
            if not self.ss_password_enc:
                self.set_ss_password()
            if not self.subscription_token_hash:
                self.set_subscription_token()
            if not self.cycle_started_at:
                self.cycle_started_at = timezone.now()
        super().save(*args, **kwargs)

    def rotate_credentials(self, *, rotate_uuid: bool = True) -> None:
        if rotate_uuid:
            self.uuid = uuid.uuid4()
        self.set_password()
        self.set_ss_password()
        self.save(
            update_fields=["uuid", "password_enc", "ss_password_enc", "updated_at"]
            if rotate_uuid
            else ["password_enc", "ss_password_enc", "updated_at"]
        )

    def rotate_subscription_token(self) -> str:
        token = self.set_subscription_token()
        self.save(update_fields=["subscription_token_hash", "subscription_token_enc", "updated_at"])
        return token

    def reset_usage(self) -> None:
        self.used_bytes = 0
        self.uploaded_bytes = 0
        self.downloaded_bytes = 0
        self.cycle_started_at = timezone.now()
        update = ["used_bytes", "uploaded_bytes", "downloaded_bytes", "cycle_started_at", "updated_at"]
        # A quota reset should make an automatically suspended user usable
        # again. Administrator-disabled and expired accounts stay disabled.
        if not self.enabled and self.disabled_reason == self.DisabledReason.QUOTA_EXCEEDED:
            self.enabled = True
            self.disabled_reason = ""
            update += ["enabled", "disabled_reason"]
        self.save(update_fields=update)

    def disable(self, reason: str = DisabledReason.DISABLED) -> None:
        self.enabled = False
        self.disabled_reason = reason
        self.save(update_fields=["enabled", "disabled_reason", "updated_at"])

    def enable(self) -> None:
        self.enabled = True
        self.disabled_reason = ""
        if self.quota_cycle == self.QuotaCycle.MONTHLY and not self.cycle_started_at:
            self.cycle_started_at = timezone.now()
        self.save(update_fields=["enabled", "disabled_reason", "cycle_started_at", "updated_at"])

    def roll_month_if_needed(self, now: datetime | None = None) -> bool:
        if self.quota_cycle != self.QuotaCycle.MONTHLY:
            return False
        now = now or timezone.now()
        started = timezone.localtime(self.cycle_started_at or self.created_at)
        current = timezone.localtime(now)
        if (started.year, started.month) == (current.year, current.month):
            return False
        self.used_bytes = 0
        self.uploaded_bytes = 0
        self.downloaded_bytes = 0
        self.cycle_started_at = now
        update = ["used_bytes", "uploaded_bytes", "downloaded_bytes", "cycle_started_at", "updated_at"]
        if not self.enabled and self.disabled_reason == self.DisabledReason.QUOTA_EXCEEDED:
            self.enabled = True
            self.disabled_reason = ""
            update += ["enabled", "disabled_reason"]
        self.save(update_fields=update)
        return True

    # -- status ----------------------------------------------------------------

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @property
    def is_over_quota(self) -> bool:
        return self.quota_bytes > 0 and self.used_bytes >= self.quota_bytes

    @property
    def status(self) -> str:
        if not self.enabled:
            return self.disabled_reason or self.DisabledReason.DISABLED
        if self.is_expired:
            return "expired"
        if self.is_over_quota:
            return "quota_exceeded"
        return "active"

    @property
    def is_active(self) -> bool:
        return self.enabled and not self.is_expired and not self.is_over_quota

    @property
    def quota_percent(self) -> float | None:
        if self.quota_bytes <= 0:
            return None
        return min(100.0, round(self.used_bytes * 100.0 / self.quota_bytes, 1))

    @property
    def remaining_bytes(self) -> int | None:
        if self.quota_bytes <= 0:
            return None
        return max(0, self.quota_bytes - self.used_bytes)

    @property
    def is_online(self) -> bool:
        if not self.last_seen_at:
            return False
        return (timezone.now() - self.last_seen_at).total_seconds() < 60


class Inbound(models.Model):
    class Kind(models.TextChoices):
        VLESS = "vless", "VLESS Reality"
        HYSTERIA2 = "hysteria2", "Hysteria2"
        TROJAN = "trojan", "Trojan"
        SHADOWSOCKS = "shadowsocks", "Shadowsocks 2022"

    DEFAULT_PORTS = {
        Kind.VLESS: 443,
        Kind.HYSTERIA2: 443,
        Kind.TROJAN: 443,
        Kind.SHADOWSOCKS: 8388,
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=16, choices=Kind.choices, unique=True)
    enabled = models.BooleanField(default=False)
    # A proxy server deliberately listens on all interfaces.
    listen = models.CharField(max_length=64, default="0.0.0.0")  # nosec B104
    port = models.PositiveIntegerField(default=443)
    certificate = models.ForeignKey(
        "certificates.Certificate",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="inbounds",
    )
    params_enc = models.TextField(editable=False, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("kind",)
        verbose_name = _("inbound")
        verbose_name_plural = _("inbounds")

    def __str__(self) -> str:
        return self.get_kind_display()

    @property
    def label(self) -> str:
        return self.get_kind_display()

    @property
    def short_label(self) -> str:
        return {
            self.Kind.VLESS: "Reality",
            self.Kind.HYSTERIA2: "Hysteria2",
            self.Kind.TROJAN: "Trojan",
            self.Kind.SHADOWSOCKS: "SS2022",
        }[self.kind]

    @property
    def params(self) -> dict:
        if not self.params_enc:
            return {}
        return decrypt_json(self, "params_enc", self.params_enc)

    def set_params(self, params: dict) -> None:
        self.params_enc = encrypt_json(self, "params_enc", params)

    def update_params(self, **values) -> None:
        params = self.params
        params.update(values)
        self.set_params(params)

    def ensure_defaults(self) -> None:
        """Populate protocol secrets required for a usable inbound."""

        params = self.params
        changed = False
        if self.kind == self.Kind.VLESS:
            if not params.get("private_key") or not params.get("public_key"):
                private_key, public_key = generate_reality_keypair()
                params.update(
                    {
                        "private_key": private_key,
                        "public_key": public_key,
                        "short_id": params.get("short_id") or generate_short_id(),
                        "server_name": params.get("server_name") or "www.microsoft.com",
                        "handshake_server": params.get("handshake_server") or "www.microsoft.com",
                        "handshake_port": params.get("handshake_port") or 443,
                    }
                )
                changed = True
        elif self.kind == self.Kind.HYSTERIA2:
            if not params.get("obfs_password"):
                params["obfs_password"] = generate_password(18)
                changed = True
        elif self.kind == self.Kind.SHADOWSOCKS:
            if not params.get("method"):
                params["method"] = "2022-blake3-aes-128-gcm"
                changed = True
            if not params.get("server_key"):
                size = 32 if "aes-256" in params["method"] else 16
                params["server_key"] = generate_ss_key(size)
                changed = True
        if changed or not self.params_enc:
            self.set_params(params)

    def rotate_keys(self) -> None:
        if self.kind == self.Kind.VLESS:
            private_key, public_key = generate_reality_keypair()
            self.update_params(private_key=private_key, public_key=public_key, short_id=generate_short_id())
        elif self.kind == self.Kind.HYSTERIA2:
            self.update_params(obfs_password=generate_password(18))
        elif self.kind == self.Kind.SHADOWSOCKS:
            params = self.params
            size = 32 if "aes-256" in params.get("method", "") else 16
            self.update_params(server_key=generate_ss_key(size))
        self.save(update_fields=["params_enc", "updated_at"])

    @property
    def needs_certificate(self) -> bool:
        return self.kind in {self.Kind.HYSTERIA2, self.Kind.TROJAN}

    def clean(self) -> None:
        errors = []
        if not 1 <= self.port <= 65535:
            errors.append(_("Port must be between 1 and 65535."))
        if self.enabled and self.needs_certificate and self.certificate_id is None:
            errors.append(_("This protocol requires a TLS certificate."))
        if self.kind == self.Kind.SHADOWSOCKS:
            method = self.params.get("method", "")
            if not method.startswith("2022-"):
                errors.append(_("Only Shadowsocks 2022 methods are supported."))
        if self.enabled and self.kind != self.Kind.HYSTERIA2:
            # Hysteria2 is UDP; every other inbound in this project is TCP.
            conflict = (
                Inbound.objects.filter(enabled=True, port=self.port)
                .exclude(pk=self.pk)
                .exclude(kind=self.Kind.HYSTERIA2)
                .first()
            )
            if conflict is not None:
                errors.append(
                    _("TCP port %(port)s is already used by %(kind)s.")
                    % {"port": self.port, "kind": conflict.get_kind_display()}
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        if not self.params_enc:
            self.ensure_defaults()
        super().save(*args, **kwargs)

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not 1 <= self.port <= 65535:
            errors.append(_("Port must be between 1 and 65535."))
        if self.needs_certificate:
            if not self.certificate_id:
                errors.append(_("Assign a TLS certificate."))
            elif not self.certificate.is_ready:
                errors.append(_("The assigned certificate is not ready."))
        params = self.params
        if self.kind == self.Kind.VLESS and not params.get("private_key"):
            errors.append(_("Reality keypair is missing."))
        if self.kind == self.Kind.SHADOWSOCKS and not params.get("server_key"):
            errors.append(_("Shadowsocks server key is missing."))
        return [str(error) for error in errors]


class TrafficDaily(models.Model):
    user = models.ForeignKey(ProxyUser, on_delete=models.CASCADE, related_name="traffic_daily")
    day = models.DateField(default=date.today, db_index=True)
    uplink = models.BigIntegerField(default=0)
    downlink = models.BigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "day"], name="unique_user_day")]
        ordering = ("-day",)
        verbose_name = _("daily traffic")
        verbose_name_plural = _("daily traffic")

    def __str__(self) -> str:
        return f"{self.user} {self.day}"

    @property
    def total(self) -> int:
        return self.uplink + self.downlink


class StatsEpoch(models.Model):
    user = models.ForeignKey(ProxyUser, on_delete=models.CASCADE, related_name="stats_epochs")
    epoch = models.UUIDField(default=uuid.uuid4, editable=False)
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user"], condition=Q(active=True), name="one_active_epoch_per_user")
        ]
        ordering = ("-started_at",)
        verbose_name = _("stats epoch")
        verbose_name_plural = _("stats epochs")

    def __str__(self) -> str:
        return f"{self.user} {self.epoch}"


__all__ = [
    "Inbound",
    "ProxyUser",
    "StatsEpoch",
    "TrafficDaily",
    "generate_password",
    "generate_reality_keypair",
    "generate_short_id",
    "generate_ss_key",
    "generate_subscription_token",
    "hash_subscription_token",
    "validate_user_name",
]
