import logging
import os

from django.core.mail import EmailMessage, send_mass_mail
from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.urls import reverse
from members.models import User

logger = logging.getLogger(__name__)


def send_meeting_reminders(meeting):
    """
    Sends two types of emails:
    1. To assigned people: "Don't forget your role!"
    2. To unassigned people: "We need help!"
    """
    messages = []
    sender = settings.DEFAULT_FROM_EMAIL
    domain = settings.SITE_URL

    # Remind people who already have a role
    assignments = meeting.roles.filter(user__isnull=False)
    for assignment in assignments:
        user = assignment.user
        if not user.email:
            continue

        if assignment.in_person is True:
            mode = " (In Person)"
        elif assignment.in_person is False:
            mode = " (Remote)"
        else:
            mode = ""

        subject = f"Reminder: You are {assignment.role.name} on {meeting.date.date()}"
        body = (
            f"Hi {user.first_name},\n\n"
            f"This is a reminder that you are signed up as **{assignment.role.name}**{mode} "
            f"for the meeting on {meeting.date.strftime('%A, %B %d')}.\n\n"
            f"Please arrive by {meeting.date.strftime('%I:%M %p')}.\n"
            f"Theme: {meeting.theme}\n\n"
            f"See the agenda here: {domain}{reverse('meeting_agenda', args=[meeting.id])}"
        )
        messages.append((subject, body, sender, [user.email]))

    # Ask unassigned members to fill open roles
    open_roles = meeting.roles.filter(user__isnull=True)
    if open_roles.exists():
        assigned_user_ids = assignments.values_list("user_id", flat=True)
        unassigned_members = User.objects.filter(
            is_active=True, is_guest=False
        ).exclude(id__in=assigned_user_ids)

        role_list = "\n".join([f"- {r.role.name}" for r in open_roles])

        for member in unassigned_members:
            if not member.email:
                continue

            subject = f"Roles needed for {meeting.date.date()}"
            body = (
                f"Hi {member.first_name},\n\n"
                f"We still have open roles for the meeting on {meeting.date.strftime('%A, %B %d')}!\n\n"
                f"Can you take one of these?\n"
                f"{role_list}\n\n"
                f"Click here to sign up instantly: {domain}{reverse('role_signups')}\n"
                f"View the full agenda: {domain}{reverse('meeting_agenda', args=[meeting.id])}"
            )
            messages.append((subject, body, sender, [member.email]))

    try:
        return send_mass_mail(tuple(messages), fail_silently=False)
    except Exception:
        logger.exception("Failed to send meeting reminders for %s", meeting)
        raise


def send_meeting_feedback(meeting):
    """
    Sends two types of post-meeting emails, each at most once per recipient:
    1. Role feedback to members who have 'admin_notes' on their role. Re-sent
       only when the notes are edited after a previous send.
    2. Thank-you emails to guests who attended (once per guest).
    """
    from django.utils import timezone
    from .models import Attendance, MeetingRole

    messages = []
    sender = settings.DEFAULT_FROM_EMAIL
    meeting_date = meeting.date.strftime("%A, %B %d")

    # Role feedback for members whose admin_notes is new or changed since the
    # last send. feedback_sent_notes holds the content last emailed.
    roles_to_stamp = []
    roles_with_feedback = meeting.roles.exclude(admin_notes="").exclude(
        user__isnull=True
    )

    count = 0
    for assignment in roles_with_feedback:
        user = assignment.user
        if not user.email:
            continue
        if assignment.admin_notes == assignment.feedback_sent_notes:
            continue

        subject = f"Feedback: Your role as {assignment.role.name}"
        body = (
            f"Hi {user.first_name},\n\n"
            f"Thank you for taking the role of **{assignment.role.name}** at our meeting on {meeting_date}.\n\n"
            f"Here are the notes/feedback regarding your role:\n"
            f"----------------------------------------------------\n"
            f"{assignment.admin_notes}\n"
            f"----------------------------------------------------\n\n"
            f"See you at the next meeting!\n"
            f"SpeakUp Team"
        )

        messages.append((subject, body, sender, [user.email]))
        roles_to_stamp.append(assignment)
        count += 1

    # Thank-you emails to guests not yet thanked
    attendances_to_stamp = []
    guest_attendances = meeting.attendances.filter(
        models.Q(user__is_guest=True) | models.Q(user__isnull=True, guest_email__gt="")
    ).filter(thank_you_sent_at__isnull=True)

    guest_count = 0
    for attendance in guest_attendances:
        if attendance.user:
            name = attendance.user.first_name
            email = attendance.user.email
        else:
            name = attendance.guest_first_name or "Guest"
            email = attendance.guest_email

        if not email:
            continue

        subject = f"Thanks for visiting SpeakUp on {meeting_date}!"
        body = (
            f"Hi {name},\n\n"
            f"Thank you for joining us at our meeting on {meeting_date}! "
            f"We hope you enjoyed the experience.\n\n"
            f"We'd love to see you again at our next meeting. "
            f"Feel free to reply to this email if you have any questions.\n\n"
            f"SpeakUp Team"
        )

        messages.append((subject, body, sender, [email]))
        attendances_to_stamp.append(attendance)
        guest_count += 1

    try:
        send_mass_mail(tuple(messages), fail_silently=False)
    except Exception:
        logger.exception("Failed to send meeting feedback for %s", meeting)
        raise

    # Record what went out, only after a successful batch send, so repeated
    # button clicks don't re-send the same feedback.
    if roles_to_stamp:
        for assignment in roles_to_stamp:
            assignment.feedback_sent_notes = assignment.admin_notes
        MeetingRole.objects.bulk_update(roles_to_stamp, ["feedback_sent_notes"])
    if attendances_to_stamp:
        now = timezone.now()
        for attendance in attendances_to_stamp:
            attendance.thank_you_sent_at = now
        Attendance.objects.bulk_update(attendances_to_stamp, ["thank_you_sent_at"])

    return count, guest_count


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
