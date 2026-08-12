import logging

logger = logging.getLogger(__name__)


def send_announcement(announcement, edits=None):
    """Send one announcement to its filtered audience. ``edits`` optionally
    overrides the subject/body (supplied by the review-before-send page).
    Returns the number of emails sent."""
    return send_announcements([announcement], edits)


def send_announcements(announcements, edits=None):
    """Send several announcements over one connection.

    Built as one batch so the whole set is dispatched together, the way the
    review page presented it — a partial send would leave the officer unsure
    which ones actually went out.
    """
    from .emails import build_announcement_draft, build_messages, send_messages

    announcements = list(announcements)
    if not announcements:
        return 0
    groups = build_announcement_draft(announcements)["groups"]
    messages = build_messages(groups, edits)
    try:
        return send_messages(messages)
    except Exception:
        logger.exception(
            "Failed to send announcements: %s",
            ", ".join(str(a) for a in announcements),
        )
        raise
