"""Security middleware: forced password change and TOTP enforcement."""

from __future__ import annotations

import ipaddress
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django_otp.plugins.otp_totp.models import TOTPDevice


def _exempt(path: str) -> bool:
    return (
        path.startswith(settings.STATIC_URL)
        or path.startswith("/api/")
        or path.startswith("/sub/")
        or path.startswith("/health")
        or path == "/favicon.ico"
        or path in {"/robots.txt"}
        or path.startswith("/accounts/login")
        or path.startswith("/accounts/logout")
        or path.startswith("/accounts/otp")
        or path.startswith("/accounts/totp/setup")
        or path.startswith("/admin/login")
        or path.startswith("/admin/logout")
    )


def _public_console_configured() -> bool:
    if settings.OSTIUM_REQUIRE_TOTP:
        return True
    if settings.OSTIUM_PUBLIC_BASE_URL.startswith("https://"):
        return True
    try:
        from constance import config

        return bool(config.public_base_url) and str(config.public_base_url).startswith("https://")
    except Exception:
        return False


class ProxyClientIPMiddleware:
    """Normalize the client address when Caddy is the trusted last hop.

    django-axes and django-ratelimit both read REMOTE_ADDR. Without this,
    every request through Caddy shares 127.0.0.1 and a single rate-limit or
    lockout bucket.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if settings.OSTIUM_BEHIND_PROXY:
            forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
            if forwarded:
                candidate = forwarded.split(",")[-1].strip()
                try:
                    ipaddress.ip_address(candidate)
                except ValueError:
                    pass
                else:
                    request.META["REMOTE_ADDR"] = candidate
        return self.get_response(request)


class AdminCSPMiddleware:
    """Allow Unfold's standard Alpine build on staff-only admin pages.

    The Aurora console uses the Alpine CSP build and keeps ``unsafe-eval``
    disabled. Unfold bundles the standard build, so the Django admin would be
    unusable under the console policy. The relaxation is scoped to ``/admin/``.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if request.path.startswith("/admin/"):
            from django.utils.csp import CSP

            config = dict(settings.SECURE_CSP)
            config["script-src"] = [CSP.SELF, CSP.NONCE, "'unsafe-eval'", "'unsafe-inline'"]
            response._csp_config = config
        return response


class AdminSecurityMiddleware:
    """Gate staff sessions behind TOTP and first-login password rotation."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not user.is_staff:
            return self.get_response(request)

        path = request.path
        if _exempt(path):
            return self.get_response(request)

        profile = getattr(user, "ostium_profile", None)
        has_totp = TOTPDevice.objects.filter(user=user, confirmed=True).exists()
        verified = bool(getattr(user, "is_verified", lambda: False)())

        password_path = path.startswith("/accounts/password/change") or path.startswith("/admin/password_change")
        if password_path:
            # A brand-new admin must be able to replace the installer password
            # before TOTP exists. Once TOTP is confirmed, password changes
            # require a verified session just like every other admin action.
            if has_totp and not verified:
                return redirect("accounts:otp")
            return self.get_response(request)

        if profile is not None and profile.must_change_password:
            return redirect("accounts:password_change")
        if has_totp and not verified:
            return redirect("accounts:otp")

        if not has_totp and profile is not None and profile.totp_required and _public_console_configured():
            return redirect("accounts:totp_setup")

        return self.get_response(request)
