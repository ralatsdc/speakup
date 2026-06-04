import logging

from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


class Role(models.Model):
    """A role that can be assigned at a meeting (e.g. Toastmaster, Timer, Speaker)."""

    name = models.CharField(max_length=100)
    shows_pathways_fields = models.BooleanField(
        default=False,
        help_text="When True, the sign-up dialog asks the member for their "
        "Pathways path/level/project for this role (Speaker, Ranter, etc.).",
    )
    is_evaluator_role = models.BooleanField(
        default=False,
        help_text="Marks roles that evaluate a speech, rant, or table-topics "
        "session. Used to filter admin dropdowns for MeetingRole.evaluates.",
    )
    is_evaluated_role = models.BooleanField(
        default=False,
        help_text="Marks roles that get evaluated by an evaluator role "
        "(e.g. Speaker, Ranter). Used as the target-side filter for "
        "MeetingRole.evaluates.",
    )
    points = models.IntegerField(default=1, help_text="Points for difficulty/effort")
    min_minutes = models.PositiveIntegerField(
        default=0, help_text="Standard minimum duration in minutes (0 = untimed)."
    )
    max_minutes = models.PositiveIntegerField(
        default=0,
        help_text="Standard maximum duration in minutes; equal to the minimum "
        "for a fixed duration.",
    )
    show_on_agenda = models.BooleanField(
        default=True,
        help_text="Uncheck to keep this role off the published agenda "
        "(web page and Word download) and the sign-up page, e.g. President.",
    )
    guidance_document = models.FileField(
        upload_to="role_guides/",
        blank=True,
        null=True,
        help_text="Attached to the welcome email a member receives the first "
        "time they take this role. Leave blank to skip the email.",
    )

    def __str__(self):
        return self.name


class Session(models.Model):
    """A reusable meeting segment (e.g. Table Topics, Prepared Speeches, Break)."""

    name = models.CharField(max_length=100)
    duration_minutes = models.PositiveIntegerField(default=0, help_text="Expected duration in minutes")
    takes_roles = models.BooleanField(default=True, help_text="Uncheck for breaks or segments that don't have assigned roles")

    def __str__(self):
        return self.name


class MeetingType(models.Model):
    """A reusable template that defines which roles a meeting needs (e.g. "Regular Meeting")."""

    name = models.CharField(max_length=100)
    zoom_link = models.URLField(blank=True)

    def __str__(self):
        return self.name


class MeetingTypeSession(models.Model):
    """Links a Session to a MeetingType with ordering."""

    meeting_type = models.ForeignKey(
        MeetingType, on_delete=models.CASCADE, related_name="sessions"
    )
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    note = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0, help_text="Order in the agenda")

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.meeting_type}: {self.session}"


class MeetingTypeItem(models.Model):
    """One line in a MeetingType template: 'this meeting needs N of this role'."""

    meeting_type = models.ForeignKey(
        MeetingType, on_delete=models.CASCADE, related_name="items"
    )
    session = models.ForeignKey(
        Session, on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Which session this role belongs to",
    )
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    count = models.PositiveIntegerField(default=1, help_text="How many of this role?")
    default_note = models.TextField(blank=True, help_text="Pre-filled note for this role when a meeting is created.")
    in_person = models.BooleanField(
        default=True,
        help_text="Whether this role is expected to be performed in person at this meeting type. "
        "Used as the dialog default at sign-up; members can override.",
    )
    order = models.PositiveIntegerField(default=0, help_text="Order in the agenda")

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.meeting_type}: {self.role} x{self.count}"


class Meeting(models.Model):
    """A scheduled club meeting."""

    meeting_type = models.ForeignKey(
        MeetingType, on_delete=models.SET_NULL, null=True, blank=True
    )
    date = models.DateTimeField()
    theme = models.CharField(max_length=200, blank=True)
    word_of_the_day = models.CharField(max_length=50, blank=True)

    zoom_link = models.URLField(blank=True)

    def __str__(self):
        return f"{self.date.strftime('%Y-%m-%d')} ({self.meeting_type})"


class MeetingSession(models.Model):
    """A session instance for a specific Meeting, populated from the MeetingType template."""

    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="meeting_sessions")
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    note = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order"]

    def __str__(self):
        return f"{self.meeting} - {self.session}"


class MeetingRole(models.Model):
    """Assigns a User to a Role for a specific Meeting."""

    # The 11 official Toastmasters Pathways learning paths.
    PATHWAYS_PATHS = [
        ("Dynamic Leadership", "Dynamic Leadership"),
        ("Effective Coaching", "Effective Coaching"),
        ("Engaging Humor", "Engaging Humor"),
        ("Innovative Planning", "Innovative Planning"),
        ("Leadership Development", "Leadership Development"),
        ("Motivational Strategies", "Motivational Strategies"),
        ("Persuasive Influence", "Persuasive Influence"),
        ("Presentation Mastery", "Presentation Mastery"),
        ("Strategic Relationships", "Strategic Relationships"),
        ("Team Collaboration", "Team Collaboration"),
        ("Visionary Communication", "Visionary Communication"),
    ]
    PATHWAYS_LEVELS = [(level, str(level)) for level in range(1, 6)]

    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="roles")
    role = models.ForeignKey(Role, on_delete=models.PROTECT)
    session = models.ForeignKey(Session, on_delete=models.SET_NULL, null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_roles",
    )
    in_person = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        help_text="Whether the assigned member attends in person. "
        "Null until a member signs up.",
    )
    exact_minutes = models.PositiveIntegerField(
        default=0,
        help_text="Exact duration for this assignment, overriding the role's "
        "standard range. 0 = use the range.",
    )
    notes = models.TextField(blank=True, help_text="Speech title, project details, or feedback.")
    admin_notes = models.TextField(blank=True, help_text="Private feedback or details for the follow-up email.")
    feedback_sent_notes = models.TextField(
        blank=True,
        default="",
        editable=False,
        help_text="The admin_notes content last emailed as feedback. Lets the "
        "feedback button send once per member, then re-send only when the "
        "notes are edited.",
    )

    pathways_path = models.CharField(
        max_length=50,
        blank=True,
        choices=PATHWAYS_PATHS,
        help_text="Toastmasters Pathways path the member is working (speech roles).",
    )
    pathways_level = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        choices=PATHWAYS_LEVELS,
        help_text="Pathways level 1–5.",
    )
    pathways_project = models.CharField(
        max_length=200,
        blank=True,
        help_text="Pathways project name for this speech.",
    )

    # For an evaluator role (Evaluator (Speech), Evaluator (Rant)), the
    # MeetingRole being evaluated. Reverse: speaker.evaluators returns the
    # evaluator MeetingRole(s) pointing at this row. Cleared on the target's
    # deletion (SET_NULL) so an evaluator slot survives if its speaker is
    # removed.
    evaluates = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="evaluators",
        help_text="For an evaluator role, the MeetingRole this evaluator "
        "is evaluating (must be on the same meeting).",
    )

    sort_order = models.PositiveIntegerField(default=0)

    def clean(self):
        super().clean()
        if self.evaluates_id is None:
            return
        if self.role_id and not self.role.is_evaluator_role:
            raise ValidationError(
                {"evaluates": "Only evaluator roles can target another row."}
            )
        if self.evaluates_id == self.id:
            raise ValidationError({"evaluates": "A role cannot evaluate itself."})
        if self.evaluates.meeting_id != self.meeting_id:
            raise ValidationError(
                {"evaluates": "evaluates must be on the same meeting."}
            )
        if not self.evaluates.role.is_evaluated_role:
            raise ValidationError(
                {"evaluates": "The target row's role is not an evaluated role."}
            )

    def attendance_label(self):
        """'In Person' / 'Remote' / '' — shared by the web and Word agendas."""
        if self.in_person is True:
            return "In Person"
        if self.in_person is False:
            return "Remote"
        return ""

    def duration_label(self):
        """Duration shown on the agendas: the exact override if set, else the
        role's standard range ('5–7 min', or 'N min' when fixed), else ''."""
        if self.exact_minutes:
            return f"{self.exact_minutes} min"
        lo, hi = self.role.min_minutes, self.role.max_minutes
        if not (lo or hi):
            return ""
        if lo and hi and lo != hi:
            return f"{lo}–{hi} min"
        return f"{hi or lo} min"

    def pathways_label(self):
        """Speaker's Pathways summary, e.g. 'Presentation Mastery L2,
        "Project Title"'. Empty parts are omitted; returns '' if none set."""
        parts = []
        if self.pathways_path:
            label = self.pathways_path
            if self.pathways_level:
                label += f" L{self.pathways_level}"
            parts.append(label)
        if self.pathways_project:
            parts.append(f'"{self.pathways_project}"')
        return ", ".join(parts)

    def agenda_notes(self):
        """Notes-column text for the agenda: Pathways summary and the speech
        notes joined by an em dash, whichever are present."""
        pathways = self.pathways_label()
        if pathways and self.notes:
            return f"{pathways} — {self.notes}"
        return pathways or self.notes

    def evaluating_label(self):
        """For an evaluator row, 'evaluating <speaker>'; '' otherwise."""
        if self.evaluates_id and self.evaluates.user:
            u = self.evaluates.user
            return f"evaluating {u.first_name} {u.last_name}"
        return ""

    def evaluated_by_label(self):
        """For an evaluated row, 'evaluator: <name>'; '' otherwise."""
        evaluator = self.evaluators.first()
        if evaluator and evaluator.user:
            u = evaluator.user
            return f"evaluator: {u.first_name} {u.last_name}"
        return ""

    def __str__(self):
        assigned = self.user.username if self.user else "OPEN"
        return f"{self.meeting} - {self.role}: {assigned}"


class Attendance(models.Model):
    """Records who attended a meeting. Links to a User for members, or stores
    guest_name/guest_email for walk-in guests."""

    meeting = models.ForeignKey(
        Meeting, on_delete=models.CASCADE, related_name="attendances"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    guest_first_name = models.CharField(max_length=50, blank=True)
    guest_last_name = models.CharField(max_length=50, blank=True)
    guest_email = models.EmailField(blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)
    thank_you_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        help_text="When the guest thank-you email was last sent. Null until "
        "sent; keeps repeated feedback runs from re-thanking a guest.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["meeting", "user"],
                condition=models.Q(user__isnull=False),
                name="unique_member_attendance",
            ),
        ]

    def __str__(self):
        if self.user:
            return f"{self.user} @ {self.meeting}"
        return f"{self.guest_first_name} {self.guest_last_name} (Guest) @ {self.meeting}"


class RoleGuideEmailLog(models.Model):
    """One row per (user, role) the moment we've sent the first-time
    role-guide email. Acts as the idempotency record so the email is sent
    at most once per member per role, even if the member is unassigned and
    later reassigned to a row of the same role.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="role_guide_emails",
    )
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "role"], name="unique_role_guide_email_per_user_role"
            ),
        ]

    def __str__(self):
        return f"{self.user} ← {self.role} guide ({self.sent_at:%Y-%m-%d})"


@receiver(post_save, sender=Meeting)
def populate_meeting_from_type(sender, instance, created, raw=False, **kwargs):
    """Auto-create MeetingSession and MeetingRole rows from the MeetingType template.

    Skips fixture loads (``raw=True``): during ``loaddata`` the template rows
    are already in the fixture, so populating again would duplicate them (this
    is what the pg.sh -c/-u dumpdata|loaddata pipeline relies on).
    """
    if raw:
        return
    if created and instance.meeting_type:
        try:
            if instance.meeting_type.zoom_link and not instance.zoom_link:
                instance.zoom_link = instance.meeting_type.zoom_link
                instance.save(update_fields=["zoom_link"])
            for mts in instance.meeting_type.sessions.select_related("session"):
                MeetingSession.objects.create(
                    meeting=instance,
                    session=mts.session,
                    note=mts.note,
                    sort_order=mts.order,
                )
            for item in instance.meeting_type.items.select_related("role"):
                for i in range(item.count):
                    MeetingRole.objects.create(
                        meeting=instance,
                        role=item.role,
                        session=item.session,
                        notes=item.default_note,
                        sort_order=item.order,
                    )
        except Exception:
            logger.exception("Failed to populate meeting %s from type", instance)


@receiver(post_save, sender=MeetingRole)
def send_first_time_role_email_on_assignment(sender, instance, created, raw=False, **kwargs):
    """Send a one-time welcome email with the role-guidance attachment the
    first time a member is assigned to a given role. Idempotency is anchored
    on RoleGuideEmailLog (user, role); existing pre-feature assignments were
    backfilled by migration so members aren't re-onboarded retroactively.

    Skips fixture loads (``raw=True``) so a dumpdata|loaddata copy of existing
    assignments doesn't email everyone.
    """
    if raw or instance.user_id is None:
        return
    # Lazy import keeps models.py free of email/utils coupling and avoids
    # circular import (utils imports from members.models).
    from .utils import send_first_time_role_email

    try:
        send_first_time_role_email(instance)
    except Exception:
        logger.exception(
            "Failed to send first-time role email for MeetingRole %s", instance.pk
        )
