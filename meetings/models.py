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
    is_speech_role = models.BooleanField(default=False)
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
    time_minutes = models.PositiveIntegerField(default=0, help_text="Expected duration in minutes")

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
    time_minutes = models.PositiveIntegerField(default=0, help_text="Expected duration in minutes")
    notes = models.TextField(blank=True, help_text="Speech title, project details, or feedback.")
    admin_notes = models.TextField(blank=True, help_text="Private feedback or details for the follow-up email.")

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


@receiver(post_save, sender=Meeting)
def populate_meeting_from_type(sender, instance, created, **kwargs):
    """Auto-create MeetingSession and MeetingRole rows from the MeetingType template."""
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
                        time_minutes=item.role.time_minutes,
                        notes=item.default_note,
                        sort_order=item.order,
                    )
        except Exception:
            logger.exception("Failed to populate meeting %s from type", instance)
