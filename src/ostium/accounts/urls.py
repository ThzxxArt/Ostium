"""Account URLs."""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.OstiumLoginView.as_view(), name="login"),
    path("logout/", views.OstiumLogoutView.as_view(), name="logout"),
    path("otp/", views.otp_verify, name="otp"),
    path("totp/setup/", views.totp_setup, name="totp_setup"),
    path("totp/recovery/", views.totp_recovery, name="totp_recovery"),
    path("totp/disable/", views.totp_disable, name="totp_disable"),
    path("password/change/", views.OstiumPasswordChangeView.as_view(), name="password_change"),
]
