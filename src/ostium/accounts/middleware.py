"""Security middleware: forced password change and TOTP enforcement."""

from __future__ import annotations

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
        or path.startswith("/accounts/password/change")
        or path.startswith("/admin/login")
        or path.startswith("/admin/logout")
        or path.startswith("/admin/password_change")
    )


def _public_console_configured() -> bool:
    if settings.OSTIUM_REQUIRE_TOTP:
        return True
    try:
        from constance import config

        return bool(config.public_base_url) and str(config.public_base_url).startswith("https://")
    except Exception:
        return False


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
        if profile is not None and profile.must_change_password:
            return redirect("accounts:password_change")

        has_totp = TOTPDevice.objects.filter(user=user, confirmed=True).exists()
        verified = bool(getattr(user, "is_verified", lambda: False)())
        if has_totp and not verified:
            return redirect("accounts:otp")

        if not has_totp and profile is not None and profile.totp_required and _public_console_configured():
            return redirect("accounts:totp_setup")

        return self.get_response(request)
