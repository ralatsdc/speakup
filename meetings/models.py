import logging

from django.db import models
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


class Role(models.Model):
    """A role that can be assigned at a meeting (e.g. Toastmaster, Timer, Speaker)."""

    name = models.CharField(max_length=100)
    is_speech_role = models.BooleanField(default=False)
    points = models.IntegerField(default=1, help_text="Points for difficulty/effort")
    time_minutes = models.PositiveIntegerField(default=0, help_text="Expected duration in minutes")
    in_person = models.BooleanField(default=True, help_text="Uncheck for roles that can be done remotely")

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
    in_person = models.BooleanField(default=True, help_text="Uncheck for roles done remotely")
    time_minutes = models.PositiveIntegerField(default=0, help_text="Expected duration in minutes")
    notes = models.TextField(blank=True, help_text="Speech title, project details, or feedback.")
    admin_notes = models.TextField(blank=True, help_text="Private feedback or details for the follow-up email.")

    sort_order = models.PositiveIntegerField(default=0)

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
                        in_person=item.role.in_person,
                        time_minutes=item.role.time_minutes,
                        notes=item.default_note,
                        sort_order=item.order,
                    )
        except Exception:
            logger.exception("Failed to populate meeting %s from type", instance)
