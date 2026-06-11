"""Passwordless ("magic link") sign-in.

A member enters their email; if it's registered we email a one-tap sign-in
link. This is the zero-setup path for first sign-in: new and imported members
have no password they know, but a magic link logs them straight in. They can
later set a password from their account page.
"""

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from communications.emails import send_simple

from .tokens import make_login_token, read_login_token

User = get_user_model()


@require_http_methods(["GET", "POST"])
def magic_link_request(request):
    """Email a sign-in link. Always shows the same confirmation regardless of
    whether the address is registered, so the page can't be used to discover
    which emails have accounts."""
    if request.method == "GET":
        return redirect("login")

    email = (request.POST.get("email") or "").strip().lower()
    if email:
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is not None:
            _send_login_link(request, user)

    return render(request, "registration/magic_link_sent.html", {"email": email})


def magic_link_login(request, token):
    """Consume a sign-in link and log the member in."""
    user = read_login_token(token, settings.MAGIC_LINK_MAX_AGE)
    if user is None or not user.is_active:
        return render(request, "registration/magic_link_invalid.html", status=400)

    login(request, user, backend="members.auth.EmailBackend")
    return redirect(settings.LOGIN_REDIRECT_URL)


def _send_login_link(request, user):
    path = reverse("magic_link_login", args=[make_login_token(user)])
    link = f"{settings.SITE_URL}{path}"
    body = (
        f"Hi {user.first_name or 'there'},\n\n"
        f"Use the link below to sign in to SpeakUp. It's valid for 24 hours and "
        f"can be used once.\n\n"
        f"[Sign in to SpeakUp]({link})\n\n"
        f"If you didn't request this, you can ignore this email — no one can "
        f"sign in without the link.\n"
    )
    send_simple("Your SpeakUp sign-in link", body, user.email)
