import logging

from django.core.mail import send_mass_mail

logger = logging.getLogger(__name__)


def send_announcement(announcement, edits=None):
    """Send an announcement to its filtered audience. ``edits`` optionally
    overrides the subject/body (supplied by the review-before-send page).
    Returns the number of emails sent."""
    from .emails import build_announcement_draft, render_messages

    messages = render_messages(build_announcement_draft(announcement)["groups"], edits)
    try:
        return send_mass_mail(messages, fail_silently=False)
    except Exception:
        logger.exception("Failed to send announcement: %s", announcement)
        raise
