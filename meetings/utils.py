from django.core.mail import send_mass_mail
from django.conf import settings
from django.urls import reverse
from members.models import User

def send_meeting_reminders(meeting, domain="http://127.0.0.1:8000"):
    """
    Sends two types of emails:
    1. To assigned people: "Don't forget your role!"
    2. To unassigned people: "We need help!"
    """
    messages = []
    sender = settings.EMAIL_HOST_USER

    # 1. Remind Assigned People
    assignments = meeting.roles.filter(user__isnull=False)
    for assignment in assignments:
        user = assignment.user
        if not user.email:
            continue

        subject = f"Reminder: You are {assignment.role.name} on {meeting.date.date()}"
        body = (
            f"Hi {user.first_name},\n\n"
            f"This is a reminder that you are signed up as **{assignment.role.name}** "
            f"for the meeting on {meeting.date.strftime('%A, %B %d')}.\n\n"
            f"Please arrive by {meeting.date.strftime('%I:%M %p')}.\n"
            f"Theme: {meeting.theme}\n\n"
            f"See the agenda here: {domain}{reverse('upcoming_meetings')}"
        )
        messages.append((subject, body, sender, [user.email]))

    # 2. Beg for Help (Open Roles)
    open_roles = meeting.roles.filter(user__isnull=True)
    if open_roles.exists():
        # Get active members who are NOT already assigned a role
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
                f"Click here to sign up instantly: {domain}{reverse('upcoming_meetings')}"
            )
            messages.append((subject, body, sender, [member.email]))

    # Send all at once
    return send_mass_mail(tuple(messages), fail_silently=False)
