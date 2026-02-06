from django.db import models
from django.conf import settings
from django.db.models.signals import post_save  # Import signals
from django.dispatch import receiver


# 2. Existing Role Model (No changes needed)
class Role(models.Model):
    name = models.CharField(max_length=100)  # e.g., Toastmaster, Timer, Ah-Counter
    is_speech_role = models.BooleanField(default=False)
    points = models.IntegerField(default=1, help_text="Points for difficulty/effort")

    def __str__(self):
        return self.name


# 1. New Model: Defines the template
class MeetingType(models.Model):
    name = models.CharField(max_length=100)  # e.g., "Regular Meeting"
    default_roles = models.ManyToManyField(Role, related_name="meeting_types")

    def __str__(self):
        return self.name


# 3. Update Meeting Model: Add the link
class Meeting(models.Model):
    meeting_type = models.ForeignKey(
        MeetingType, on_delete=models.SET_NULL, null=True, blank=True
    )
    date = models.DateTimeField()
    theme = models.CharField(max_length=200, blank=True)
    word_of_the_day = models.CharField(max_length=50, blank=True)

    # If you meet hybrid/online
    zoom_link = models.URLField(blank=True)

    def __str__(self):
        return f"{self.date.strftime('%Y-%m-%d')} ({self.meeting_type})"


class MeetingRole(models.Model):
    """
    The Pivot Table: Assigns a User to a Role for a specific Meeting.
    """

    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="roles")
    role = models.ForeignKey(Role, on_delete=models.PROTECT)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_roles",
    )

    # If someone backs out, who fills in?
    backup_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="backup_roles",
    )

    class Meta:
        unique_together = ("meeting", "role")  # One Toastmaster per meeting

    def __str__(self):
        assigned = self.user.username if self.user else "OPEN"
        return f"{self.meeting} - {self.role}: {assigned}"


class Attendance(models.Model):
    meeting = models.ForeignKey(
        Meeting, on_delete=models.CASCADE, related_name="attendances"
    )
    # Link to a member...
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    # ...OR store guest details
    guest_name = models.CharField(max_length=100, blank=True)
    guest_email = models.EmailField(blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.user:
            return f"{self.user} @ {self.meeting}"
        return f"{self.guest_name} (Guest) @ {self.meeting}"


# 4. The Automation Signal
# This function runs every time you hit "Save" on a Meeting
@receiver(post_save, sender=Meeting)
def populate_meeting_roles(sender, instance, created, **kwargs):
    if created and instance.meeting_type:
        # Get the template roles
        roles_to_add = instance.meeting_type.default_roles.all()

        # Bulk create the specific roles for this meeting
        for role in roles_to_add:
            MeetingRole.objects.get_or_create(meeting=instance, role=role)
