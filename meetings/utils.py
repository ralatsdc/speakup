import logging
import os

from django.core.mail import EmailMessage
from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.urls import reverse
from members.models import User

logger = logging.getLogger(__name__)


def send_meeting_reminders(meeting, edits=None):
    """Send role reminders (to assignees) and open-role nudges (to everyone
    unassigned). ``edits`` optionally overrides the per-group subject/body
    templates (supplied by the review-before-send page)."""
    from .emails import build_reminder_draft
    from communications.emails import build_messages, send_messages

    messages = build_messages(build_reminder_draft(meeting)["groups"], edits)
    try:
        return send_messages(messages)
    except Exception:
        logger.exception("Failed to send meeting reminders for %s", meeting)
        raise


def send_meeting_feedback(meeting, edits=None):
    """Send role feedback (members whose ``admin_notes`` is new/changed) and
    guest thank-yous (once per guest), then stamp what went out so repeats
    don't re-send. ``edits`` optionally overrides the subject/body templates.
    Returns ``(feedback_count, guest_count)``."""
    from django.utils import timezone
    from .emails import build_feedback_draft
    from .models import Attendance, MeetingRole
    from communications.emails import build_messages, send_messages

    groups = build_feedback_draft(meeting)["groups"]
    messages = build_messages(groups, edits)
    try:
        send_messages(messages)
    except Exception:
        logger.exception("Failed to send meeting feedback for %s", meeting)
        raise

    # Record what went out, only after a successful batch send.
    roles = [r["_role"] for g in groups if g["key"] == "feedback"
             for r in g["recipients"]]
    attendances = [r["_attendance"] for g in groups if g["key"] == "guests"
                   for r in g["recipients"]]
    if roles:
        for a in roles:
            a.feedback_sent_notes = a.admin_notes
        MeetingRole.objects.bulk_update(roles, ["feedback_sent_notes"])
    if attendances:
        now = timezone.now()
        for att in attendances:
            att.thank_you_sent_at = now
        Attendance.objects.bulk_update(attendances, ["thank_you_sent_at"])

    return len(roles), len(attendances)


def send_first_time_role_email(meeting_role):
    """Send a welcome email with the role's guidance document attached, the
    first time a member is assigned to that role.

    Returns True if an email was sent (and a RoleGuideEmailLog row written),
    False if skipped (no user, no email, no guidance document on the role,
    or the member has already received this role's guide).
    """
    # Imported lazily to avoid a models <-> utils cycle at app load.
    from .models import RoleGuideEmailLog

    user = meeting_role.user
    role = meeting_role.role
    if user is None or not user.email:
        return False
    if not role.guidance_document:
        return False
    if RoleGuideEmailLog.objects.filter(user=user, role=role).exists():
        return False

    # Reserve the (user, role) slot before sending. If two concurrent saves
    # race (e.g. signal fires twice), the second one hits the unique
    # constraint and bails — the member only gets one email.
    try:
        with transaction.atomic():
            RoleGuideEmailLog.objects.create(user=user, role=role)
    except IntegrityError:
        return False

    meeting = meeting_role.meeting
    meeting_date = meeting.date.strftime("%A, %B %d, %Y")
    subject = f"Your first time as {role.name} — here's a guide"
    body = (
        f"Hi {user.first_name or user.username},\n\n"
        f"You're signed up to be **{role.name}** for the meeting on "
        f"{meeting_date}. Since this is your first time taking this role, "
        f"we've attached a short guide to help you prepare.\n\n"
        f"Have a look when you get a chance, and let an officer know if you "
        f"have any questions.\n\n"
        f"See you at the meeting!\n"
        f"SpeakUp Team"
    )

    email = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )

    doc = role.guidance_document
    filename = os.path.basename(doc.name)
    try:
        with doc.open("rb") as fh:
            email.attach(filename, fh.read())
    except FileNotFoundError:
        # Storage referenced a file that's gone (e.g. media volume not
        # mounted). Roll back the log so a later assignment can retry.
        logger.exception(
            "Guidance document missing for role %s; rolling back log", role
        )
        RoleGuideEmailLog.objects.filter(user=user, role=role).delete()
        return False

    try:
        email.send(fail_silently=False)
    except Exception:
        logger.exception(
            "Failed to send first-time role email for user=%s role=%s", user, role
        )
        RoleGuideEmailLog.objects.filter(user=user, role=role).delete()
        raise
    return True


def upcoming_meetings_with_open_role(role, now=None):
    """Upcoming meetings (date >= now) that have an unfilled slot for ``role``,
    earliest first. Used to make a role invite actionable."""
    from django.utils import timezone
    from .models import Meeting

    now = now or timezone.now()
    return (
        Meeting.objects.filter(date__gte=now, roles__role=role,
                               roles__user__isnull=True)
        .distinct()
        .order_by("date")
    )


def send_role_invite(member, roles, edits=None, now=None):
    """Invite ``member`` to sign up for one of ``roles`` at an upcoming meeting.
    Lists, per role, the upcoming meetings that currently have it open (generic
    nudge if none do). ``edits`` optionally overrides the subject/body. Returns
    the number of distinct open upcoming meetings listed.

    The caller is responsible for not inviting when there are no upcoming
    meetings at all (the button is disabled in that case).
    """
    from .emails import build_invite_draft
    from communications.emails import build_messages, send_messages

    draft = build_invite_draft(member, roles, now=now)
    messages = build_messages(draft["groups"], edits)
    try:
        send_messages(messages)
    except Exception:
        logger.exception(
            "Failed to send role invite to user=%s roles=%s", member,
            [r.id for r in roles]
        )
        raise
    return draft["open_count"]
