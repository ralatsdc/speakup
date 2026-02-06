from django.db import models
from django.conf import settings

class Role(models.Model):
    name = models.CharField(max_length=100) # e.g., Toastmaster, Timer, Ah-Counter
    is_speech_role = models.BooleanField(default=False)
    points = models.IntegerField(default=1, help_text="Points for difficulty/effort")

    def __str__(self):
        return self.name

class Meeting(models.Model):
    date = models.DateTimeField()
    theme = models.CharField(max_length=200, blank=True)
    word_of_the_day = models.CharField(max_length=50, blank=True)
    
    # If you meet hybrid/online
    zoom_link = models.URLField(blank=True)
    
    def __str__(self):
        return f"Meeting on {self.date.strftime('%Y-%m-%d')}"

class MeetingRole(models.Model):
    """
    The Pivot Table: Assigns a User to a Role for a specific Meeting.
    """
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name='roles')
    role = models.ForeignKey(Role, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='meeting_roles')
    
    # If someone backs out, who fills in?
    backup_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='backup_roles')

    class Meta:
        unique_together = ('meeting', 'role') # One Toastmaster per meeting

    def __str__(self):
        assigned = self.user.username if self.user else "OPEN"
        return f"{self.meeting} - {self.role}: {assigned}"
