"""
Draft builders for the meeting-related review-gated emails (reminders,
feedback, role invites). Each returns the uniform draft structure documented
in ``communications.emails``. The actual ``send_mass_mail`` call lives in
``meetings.utils`` (so test patch targets stay put); these only build.

Fan-out workflows (reminders, feedback) expose editable templates with
``{placeholders}`` so the shared text can be tweaked once and rendered per
recipient. The single-recipient invite is pre-rendered to clean literal text.
"""

from django.conf import settings
from django.urls import reverse

from members.models import User

# --- reminder templates ----------------------------------------------------

REMINDER_ASSIGNEE_SUBJECT = "Reminder: You are {role} on {date}"
REMINDER_ASSIGNEE_BODY = (
    "Hi {first_name},\n\n"
    "This is a reminder that you are signed up as **{role}**{mode} "
    "for the meeting on {long_date}.\n\n"
    "Please arrive by {time}.\n"
    "Theme: {theme}\n\n"
    "See the agenda here: {agenda_url}"
)
REMINDER_OPEN_SUBJECT = "Roles needed for {date}"
REMINDER_OPEN_BODY = (
    "Hi {first_name},\n\n"
    "We still have open roles for the meeting on {long_date}!\n\n"
    "Can you take one of these?\n"
    "{role_list}\n\n"
    "Click here to sign up instantly: {signups_url}\n"
    "View the full agenda: {agenda_url}"
)

# --- feedback templates ----------------------------------------------------

FEEDBACK_SUBJECT = "Feedback: Your role as {role}"
FEEDBACK_BODY = (
    "Hi {first_name},\n\n"
    "Thank you for taking the role of **{role}** at our meeting on "
    "{meeting_date}.\n\n"
    "Here are the notes/feedback regarding your role:\n"
    "----------------------------------------------------\n"
    "{notes}\n"
    "----------------------------------------------------\n\n"
    "See you at the next meeting!\n"
    "SpeakUp Team"
)
GUEST_THANKS_SUBJECT = "Thanks for visiting SpeakUp on {meeting_date}!"
GUEST_THANKS_BODY = (
    "Hi {first_name},\n\n"
    "Thank you for joining us at our meeting on {meeting_date}! "
    "We hope you enjoyed the experience.\n\n"
    "We'd love to see you again at our next meeting. "
    "Feel free to reply to this email if you have any questions.\n\n"
    "SpeakUp Team"
)


def _mode(in_person):
    if in_person is True:
        return " (In Person)"
    if in_person is False:
        return " (Remote)"
    return ""


def build_reminder_draft(meeting, back_url=""):
    domain = settings.SITE_URL
    agenda_url = f"{domain}{reverse('meeting_agenda', args=[meeting.id])}"
    signups_url = f"{domain}{reverse('role_signups')}"
    long_date = meeting.date.strftime("%A, %B %d")
    groups = []

    assignments = meeting.roles.filter(user__isnull=False).select_related("user", "role")
    assignees = [
        {"email": a.user.email, "name": str(a.user), "context": {
            "first_name": a.user.first_name, "role": a.role.name,
            "mode": _mode(a.in_person), "date": meeting.date.date(),
            "long_date": long_date, "time": meeting.date.strftime("%I:%M %p"),
            "theme": meeting.theme, "agenda_url": agenda_url,
        }}
        for a in assignments if a.user.email
    ]
    if assignees:
        groups.append({
            "key": "assignees",
            "label": f"Assigned members ({len(assignees)})",
            "subject": REMINDER_ASSIGNEE_SUBJECT, "body": REMINDER_ASSIGNEE_BODY,
            "placeholders": ["first_name", "role", "mode", "date", "long_date",
                             "time", "theme", "agenda_url"],
            "recipients": assignees,
        })

    open_roles = meeting.roles.filter(user__isnull=True).select_related("role")
    if open_roles.exists():
        assigned_ids = assignments.values_list("user_id", flat=True)
        role_list = "\n".join(f"- {r.role.name}" for r in open_roles)
        nudges = [
            {"email": m.email, "name": str(m), "context": {
                "first_name": m.first_name, "date": meeting.date.date(),
                "long_date": long_date, "role_list": role_list,
                "signups_url": signups_url, "agenda_url": agenda_url,
            }}
            for m in User.objects.filter(is_active=True, is_guest=False)
            .exclude(id__in=assigned_ids) if m.email
        ]
        if nudges:
            groups.append({
                "key": "open_roles",
                "label": f"Open-role nudge ({len(nudges)})",
                "subject": REMINDER_OPEN_SUBJECT, "body": REMINDER_OPEN_BODY,
                "placeholders": ["first_name", "date", "long_date", "role_list",
                                 "signups_url", "agenda_url"],
                "recipients": nudges,
            })

    return {"workflow": "reminders", "title": f"Send reminders — {meeting.date.date()}",
            "back_url": back_url, "target": {"meeting": meeting.id}, "groups": groups}


def build_feedback_draft(meeting, back_url=""):
    from django.db.models import Q

    meeting_date = meeting.date.strftime("%A, %B %d")
    groups = []

    # Role feedback for members whose admin_notes is new/changed since last send.
    feedback = []
    for a in meeting.roles.exclude(admin_notes="").exclude(user__isnull=True) \
            .select_related("user", "role"):
        if not a.user.email or a.admin_notes == a.feedback_sent_notes:
            continue
        feedback.append({"email": a.user.email, "name": str(a.user), "_role": a,
                         "context": {"first_name": a.user.first_name,
                                     "role": a.role.name, "meeting_date": meeting_date,
                                     "notes": a.admin_notes}})
    if feedback:
        groups.append({
            "key": "feedback", "label": f"Role feedback ({len(feedback)})",
            "subject": FEEDBACK_SUBJECT, "body": FEEDBACK_BODY,
            "placeholders": ["first_name", "role", "meeting_date", "notes"],
            "recipients": feedback,
        })

    # Thank-you emails to guests not yet thanked.
    guests = []
    for att in meeting.attendances.filter(
            Q(user__is_guest=True) | Q(user__isnull=True, guest_email__gt="")
    ).filter(thank_you_sent_at__isnull=True).select_related("user"):
        if att.user:
            name, email = att.user.first_name, att.user.email
        else:
            name, email = (att.guest_first_name or "Guest"), att.guest_email
        if not email:
            continue
        guests.append({"email": email, "name": name, "_attendance": att,
                       "context": {"first_name": name, "meeting_date": meeting_date}})
    if guests:
        groups.append({
            "key": "guests", "label": f"Guest thank-yous ({len(guests)})",
            "subject": GUEST_THANKS_SUBJECT, "body": GUEST_THANKS_BODY,
            "placeholders": ["first_name", "meeting_date"],
            "recipients": guests,
        })

    return {"workflow": "feedback", "title": f"Send feedback — {meeting.date.date()}",
            "back_url": back_url, "target": {"meeting": meeting.id}, "groups": groups}


def build_invite_draft(member, role, back_url="", now=None):
    """Single-recipient invite — pre-rendered to clean literal text (no tokens),
    since there is nothing to fan out. ``open_count`` drives the status message."""
    from .utils import upcoming_meetings_with_open_role

    domain = settings.SITE_URL
    signups_url = f"{domain}{reverse('role_signups')}"
    open_meetings = list(upcoming_meetings_with_open_role(role, now=now))
    if open_meetings:
        when = "\n".join(
            f"- {m.date.strftime('%A, %B %d')}"
            f" ({m.meeting_type.name if m.meeting_type else 'meeting'})"
            for m in open_meetings)
        opening = (f"We'd love for you to take the **{role.name}** role at an "
                   f"upcoming meeting. It's currently open at:\n\n{when}\n\n")
    else:
        opening = (f"We'd love for you to take the **{role.name}** role at an "
                   f"upcoming meeting.\n\n")

    subject = f"Invitation: take the {role.name} role at SpeakUp"
    body = (
        f"Hi {member.first_name or member.username},\n\n"
        f"{opening}"
        f"You can sign up here: {signups_url}\n\n"
        f"Taking on a role is a great way to practice — and we'd love to see "
        f"you up there.\n\n"
        f"SpeakUp Team"
    )
    recipients = [{"email": member.email, "name": str(member), "context": {}}] \
        if member.email else []
    return {
        "workflow": "invite",
        "title": f"Invite {member} to take {role.name}",
        "back_url": back_url,
        "target": {"member": member.id, "role": role.id},
        "open_count": len(open_meetings),
        "groups": [{
            "key": "invite", "label": str(member),
            "subject": subject, "body": body, "placeholders": [],
            "recipients": recipients,
        }],
    }
