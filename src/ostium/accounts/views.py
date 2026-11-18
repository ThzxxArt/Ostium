"""Login, TOTP, recovery-code and password-change views."""

from __future__ import annotations

import secrets

import segno
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django_otp import login as otp_login
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_ratelimit.decorators import ratelimit

from ostium.operations.services import record_audit

from .forms import DisableOTPForm, LoginForm, OTPForm, StyledPasswordChangeForm


def _qr_data_uri(value: str) -> str:
    return segno.make(value, error="m").svg_data_uri(scale=6, border=2, dark="#0b1220", light="#ffffff")


def _pending_user(request: HttpRequest):
    user_id = request.session.get("otp_pending_user")
    if user_id:
        from django.contrib.auth import get_user_model

        return get_user_model().objects.filter(pk=user_id, is_active=True, is_staff=True).first()
    if request.user.is_authenticated and request.user.is_staff:
        return request.user
    return None


def _verify_any_device(user, token: str):
    for device in TOTPDevice.objects.filter(user=user, confirmed=True):
        if device.verify_token(token):
            return device
    for device in StaticDevice.objects.filter(user=user, confirmed=True):
        if device.verify_token(token):
            return device
    return None


@method_decorator(never_cache, name="dispatch")
class OstiumLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form) -> HttpResponse:
        user = form.get_user()
        if TOTPDevice.objects.filter(user=user, confirmed=True).exists():
            self.request.session["otp_pending_user"] = str(user.pk)
            self.request.session["otp_next"] = self.get_success_url()
            record_audit(action="auth.password_ok", request=self.request, actor=user, target=user.get_username())
            return redirect("accounts:otp")
        auth_login(self.request, user)
        record_audit(action="auth.login", request=self.request, actor=user, target=user.get_username())
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        return self.get_redirect_url() or str(reverse_lazy("console:dashboard"))


@never_cache
@ratelimit(key="ip", rate="10/m", block=True)
def otp_verify(request: HttpRequest) -> HttpResponse:
    user = _pending_user(request)
    if user is None:
        return redirect("accounts:login")

    if request.method == "POST":
        form = OTPForm(request.POST)
        if form.is_valid():
            device = _verify_any_device(user, form.cleaned_data["token"])
            if device is not None:
                auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                otp_login(request, device)
                next_url = request.session.pop("otp_next", None) or str(reverse_lazy("console:dashboard"))
                request.session.pop("otp_pending_user", None)
                record_audit(action="auth.login", request=request, actor=user, target=user.get_username())
                return redirect(next_url)
            record_audit(action="auth.otp_failed", request=request, actor=user, target=user.get_username())
            form.add_error("token", _("That code is not valid. Check your authenticator clock and try again."))
    else:
        form = OTPForm()

    return render(request, "registration/otp.html", {"form": form, "username": user.get_username()})


@login_required
@never_cache
def totp_setup(request: HttpRequest) -> HttpResponse:
    if not request.user.is_staff:
        return redirect("console:dashboard")

    confirmed = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
    if confirmed and request.user.is_verified():
        return redirect("console:dashboard")

    device, _created = TOTPDevice.objects.get_or_create(
        user=request.user,
        name="default",
        defaults={"confirmed": False},
    )
    if request.method == "POST":
        form = OTPForm(request.POST)
        if form.is_valid():
            if device.verify_token(form.cleaned_data["token"]):
                device.confirmed = True
                device.save(update_fields=["confirmed"])
                recovery = _reset_recovery_codes(request.user)
                otp_login(request, device)
                record_audit(action="auth.totp_enabled", request=request, target=request.user.get_username())
                messages.success(request, _("Two-factor authentication is now enabled."))
                return render(
                    request,
                    "registration/recovery_codes.html",
                    {"codes": recovery, "first_setup": True},
                )
            form.add_error("token", _("That code is not valid. Make sure your device clock is correct."))
    else:
        form = OTPForm()

    return render(
        request,
        "registration/totp_setup.html",
        {
            "form": form,
            "secret": device.key,
            "qr": _qr_data_uri(device.config_url),
            "already_confirmed": bool(confirmed),
        },
    )


def _reset_recovery_codes(user) -> list[str]:
    device, _created = StaticDevice.objects.get_or_create(user=user, name="recovery", defaults={"confirmed": True})
    device.confirmed = True
    device.save(update_fields=["confirmed"])
    device.token_set.all().delete()
    codes: list[str] = []
    for _index in range(10):
        token = secrets.token_hex(5)
        StaticToken.objects.create(device=device, token=token)
        codes.append(token)
    return codes


@login_required
@never_cache
def totp_recovery(request: HttpRequest) -> HttpResponse:
    codes = request.session.pop("recovery_codes", [])
    return render(request, "registration/recovery_codes.html", {"codes": codes, "first_setup": False})


@login_required
@never_cache
def totp_disable(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = DisableOTPForm(request.POST)
        if form.is_valid():
            if not request.user.check_password(form.cleaned_data["password"]):
                form.add_error("password", _("Password is incorrect."))
            elif _verify_any_device(request.user, form.cleaned_data["token"]) is None:
                form.add_error("token", _("Verification code is incorrect."))
            else:
                TOTPDevice.objects.filter(user=request.user).delete()
                StaticDevice.objects.filter(user=request.user).delete()
                record_audit(action="auth.totp_disabled", request=request, target=request.user.get_username())
                messages.success(request, _("Two-factor authentication has been disabled."))
                return redirect("console:system")
    else:
        form = DisableOTPForm()
    return render(request, "registration/totp_disable.html", {"form": form})


class OstiumPasswordChangeView(PasswordChangeView):
    template_name = "registration/password_change.html"
    form_class = StyledPasswordChangeForm
    success_url = reverse_lazy("console:dashboard")

    def form_valid(self, form) -> HttpResponse:
        response = super().form_valid(form)
        update_session_auth_hash(self.request, form.user)
        profile = getattr(self.request.user, "ostium_profile", None)
        if profile is not None and profile.must_change_password:
            profile.must_change_password = False
            profile.save(update_fields=["must_change_password"])
        record_audit(action="auth.password_changed", request=self.request, target=self.request.user.get_username())
        messages.success(self.request, _("Password updated."))
        return response


class OstiumLogoutView(LogoutView):
    next_page = reverse_lazy("accounts:login")

    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if request.user.is_authenticated:
            record_audit(action="auth.logout", request=request, target=request.user.get_username())
        return super().dispatch(request, *args, **kwargs)
