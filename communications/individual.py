"""
One-at-a-time announcement sending: the officer customizes and sends to each
recipient in turn.

An announcement is *in progress* while ``sent_at`` is unset and it has delivery
rows. It completes (``sent_at`` is set) once nobody is left and at least one
email went out. Every change locks the announcement row first, so two tabs or
two officers can't act on the same announcement at once.
"""

from contextlib import contextmanager

from django.db import transaction
from django.utils import timezone

from .emails import (announcement_recipients, build_messages, resolve_sender,
                     send_messages)
from .models import Announcement, AnnouncementDelivery


class NotAvailable(Exception):
    """The requested step no longer applies (already handled, left the
    audience, or the announcement is finished). The message is shown as is."""


def is_in_progress(announcement):
    return announcement.sent_at is None and announcement.deliveries.exists()


def handled_user_ids(announcement):
    return set(announcement.deliveries.values_list("user_id", flat=True))


def remaining(announcement):
    """Recipients in the current audience not yet sent or skipped, by name."""
    handled = handled_user_ids(announcement)
    return sorted(
        (r for r in announcement_recipients(announcement)
         if r["user_id"] not in handled),
        key=lambda r: (r["name"].lower(), r["email"]))


def everyone_skipped(announcement):
    """Nobody is left and nothing ever went out, so it was never sent."""
    return (is_in_progress(announcement)
            and not announcement.deliveries.filter(
                status=AnnouncementDelivery.SENT).exists()
            and not remaining(announcement))


def complete_if_finished(announcement):
    """Stamp ``sent_at`` if nobody is left and something was sent. Returns
    whether it did."""
    if (announcement.sent_at is None
            and announcement.deliveries.filter(
                status=AnnouncementDelivery.SENT).exists()
            and not remaining(announcement)):
        announcement.sent_at = timezone.now()
        announcement.save(update_fields=["sent_at"])
        return True
    return False


@contextmanager
def _locked(announcement_id):
    """A transaction holding the announcement's row, refusing finished ones."""
    with transaction.atomic():
        announcement = Announcement.objects.select_for_update().get(
            pk=announcement_id)
        if announcement.sent_at is not None:
            raise NotAvailable("This announcement has already been sent.")
        yield announcement


def _claim(announcement, user_id, officer, **fields):
    """Record the outcome for a recipient who is still waiting."""
    recipient = next(
        (r for r in remaining(announcement) if r["user_id"] == user_id), None)
    if recipient is None:
        raise NotAvailable(
            "That person was already handled or is no longer in the audience. "
            "Nothing was sent.")
    delivery = AnnouncementDelivery.objects.create(
        announcement=announcement, user_id=user_id, name=recipient["name"],
        email=recipient["email"], handled_by=officer, **fields)
    return recipient, delivery


def send_one(announcement_id, user_id, officer, subject, body, sender_id=""):
    """Send one recipient their copy. The record and the send share a
    transaction: if the send fails, no record is kept and it can be retried.
    Returns ``(delivery, completed)``."""
    header = resolve_sender(sender_id)
    with _locked(announcement_id) as announcement:
        recipient, delivery = _claim(
            announcement, user_id, officer,
            status=AnnouncementDelivery.SENT, sender=header)
        message, = build_messages([{
            "key": "one", "subject": subject, "body": body,
            "recipients": [recipient],
        }], {"one": {"sender": sender_id}})
        delivery.subject = message.subject
        delivery.body = message.body
        delivery.save(update_fields=["subject", "body"])
        if not send_messages([message]):
            raise RuntimeError("The email service did not accept the message.")
        completed = complete_if_finished(announcement)
    return delivery, completed


def skip_one(announcement_id, user_id, officer):
    """Returns ``(delivery, completed)``."""
    with _locked(announcement_id) as announcement:
        _, delivery = _claim(
            announcement, user_id, officer,
            status=AnnouncementDelivery.SKIPPED)
        completed = complete_if_finished(announcement)
    return delivery, completed


def restore(announcement_id, delivery_id):
    """Put a skipped recipient back in line."""
    with _locked(announcement_id) as announcement:
        deleted, _ = announcement.deliveries.filter(
            pk=delivery_id, status=AnnouncementDelivery.SKIPPED).delete()
        if not deleted:
            raise NotAvailable("That person isn’t on the skipped list.")


def complete(announcement_id):
    """Finish an announcement whose remaining recipients left the audience."""
    with _locked(announcement_id) as announcement:
        if not complete_if_finished(announcement):
            raise NotAvailable("This announcement can’t be completed yet.")
