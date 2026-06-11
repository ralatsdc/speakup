"""Member-facing transactional emails (welcome / onboarding)."""

from django.conf import settings
from django.urls import reverse

from communications.emails import send_simple


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
