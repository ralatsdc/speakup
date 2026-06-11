"""Member-facing routes: passwordless sign-in and self-service account."""

from django.urls import path

from . import auth_views

urlpatterns = [
    path("accounts/magic-link/", auth_views.magic_link_request, name="magic_link_request"),
    path("accounts/magic-link/<str:token>/", auth_views.magic_link_login, name="magic_link_login"),
]
