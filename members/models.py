from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """
    Custom user model for SpeakUp.
    Differentiates between Guests and official Members.
    """

    is_guest = models.BooleanField(default=False)
    phone_number = models.CharField(max_length=20, blank=True)

    # Club membership fields
    join_date = models.DateField(null=True, blank=True)
    is_officer = models.BooleanField(
        default=False, help_text="Can manage meeting agendas"
    )

    # Mentorship: each member may have one mentor
    mentor = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="mentees"
    )

    @property
    def status_label(self):
        if self.is_guest:
            return "Guest"
        return "Member"

    def __str__(self):
        return (
            f"{self.first_name}" if self.first_name else self.username
        )
