"""Member-facing transactional emails (welcome / onboarding, email change)."""

from django.conf import settings
from django.urls import reverse

from communications.emails import send_simple

from .tokens import make_email_change_token


def send_welcome_email(user):
    """Invite a member to sign in for the first time. Points them at the login
    page and explains the passwordless option, so a member with no password
    (new, imported, or guest-converted) can get in without anything to set up.
    Returns the number of messages accepted for delivery."""
    login_url = f"{settings.SITE_URL}{reverse('login')}"
    body = (
        f"Hi {user.first_name or 'there'},\n\n"
        f"Welcome to SpeakUp — the Speak Up Cambridge club site for meeting "
        f"sign-ups, agendas, and announcements.\n\n"
        f"To sign in, go to [{login_url}]({login_url}) and enter your email "
        f"(**{user.email}**). You don't need a password: choose "
        f"**Email me a sign-in link** and we'll send you a one-tap link. You can "
        f"set a password later from your account page if you'd prefer one.\n\n"
        f"See you at the next meeting!\n"
    )
    return send_simple("Welcome to SpeakUp", body, user.email)


def send_email_change_confirmation(user, new_email):
    """Email a confirmation link to the member's *proposed* new address. The
    change only applies when they click it, so the link goes to ``new_email``
    (not the current one). Returns the number of messages accepted."""
    path = reverse("account_email_confirm", args=[make_email_change_token(user, new_email)])
    link = f"{settings.SITE_URL}{path}"
    body = (
        f"Hi {user.first_name or 'there'},\n\n"
        f"Use the link below to confirm **{new_email}** as your new sign-in email "
        f"for SpeakUp. It's valid for 24 hours.\n\n"
        f"[Confirm this email address]({link})\n\n"
        f"If you didn't request this, you can ignore this email — your address "
        f"won't change.\n"
    )
    return send_simple("Confirm your new SpeakUp email", body, new_email)
