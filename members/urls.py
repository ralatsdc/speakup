"""Member-facing routes: passwordless sign-in and self-service account."""

from django.urls import path

from . import account_views, auth_views

urlpatterns = [
    path("accounts/magic-link/", auth_views.magic_link_request, name="magic_link_request"),
    path("accounts/magic-link/<str:token>/", auth_views.magic_link_login, name="magic_link_login"),
    path("account/", account_views.account, name="account"),
    path("account/name/", account_views.account_profile, name="account_profile"),
    path("account/password/", account_views.account_password, name="account_password"),
    path("account/email/", account_views.account_email, name="account_email"),
    path("account/email/confirm/<str:token>/", account_views.account_email_confirm, name="account_email_confirm"),
]
