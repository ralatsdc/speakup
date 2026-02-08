import logging

from django.conf import settings
from django.core.mail import send_mass_mail

logger = logging.getLogger(__name__)


def send_announcement(announcement):
    """
    Sends an announcement email to the filtered audience.
    Returns the number of emails sent.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()

    if announcement.audience == "officers":
        recipients = User.objects.filter(is_officer=True, is_active=True)
    elif announcement.audience == "guests":
        recipients = User.objects.filter(is_guest=True, is_active=True)
    else:
        recipients = User.objects.filter(is_active=True)

    messages = []
    sender = settings.DEFAULT_FROM_EMAIL

    for user in recipients:
        if user.email:
            messages.append((announcement.subject, announcement.body, sender, [user.email]))

    try:
        count = send_mass_mail(tuple(messages), fail_silently=False)
    except Exception:
        logger.exception("Failed to send announcement: %s", announcement)
        raise
    return count
