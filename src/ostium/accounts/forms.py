"""Authentication forms with conservative server-side validation."""

from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.utils.translation import gettext_lazy as _


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label=_("Username"),
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True}),
    )
    password = forms.CharField(
        label=_("Password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": _("Username or password is incorrect."),
        "inactive": _("This account is disabled."),
    }


class OTPForm(forms.Form):
    token = forms.CharField(
        label=_("Verification code"),
        max_length=16,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "autofocus": True,
                "placeholder": "000000",
            }
        ),
    )

    def clean_token(self) -> str:
        return self.cleaned_data["token"].strip().replace(" ", "")


class DisableOTPForm(forms.Form):
    password = forms.CharField(
        label=_("Current password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    token = forms.CharField(label=_("Verification code"), max_length=16)


class StyledPasswordChangeForm(PasswordChangeForm):
    pass
