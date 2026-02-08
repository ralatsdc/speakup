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

    def __str__(self):
        return self.name


class MeetingType(models.Model):
    """A reusable template that defines which roles a meeting needs (e.g. "Regular Meeting")."""

    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class MeetingTypeItem(models.Model):
    """One line in a MeetingType template: 'this meeting needs N of this role'."""

    meeting_type = models.ForeignKey(
        MeetingType, on_delete=models.CASCADE, related_name="items"
    )
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    count = models.PositiveIntegerField(default=1, help_text="How many of this role?")
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


class MeetingRole(models.Model):
    """Assigns a User to a Role for a specific Meeting."""

    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="roles")
    role = models.ForeignKey(Role, on_delete=models.PROTECT)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_roles",
    )
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
    guest_name = models.CharField(max_length=100, blank=True)
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
        return f"{self.guest_name} (Guest) @ {self.meeting}"


@receiver(post_save, sender=Meeting)
def populate_meeting_roles(sender, instance, created, **kwargs):
    """Auto-create MeetingRole rows from the MeetingType template when a new Meeting is saved."""
    if created and instance.meeting_type:
        try:
            for item in instance.meeting_type.items.all():
                for i in range(item.count):
                    MeetingRole.objects.create(
                        meeting=instance,
                        role=item.role,
                        sort_order=item.order,
                    )
        except Exception:
            logger.exception("Failed to populate roles for meeting %s", instance)
