from django.db import models
from django.conf import settings
from django.core.mail import send_mass_mail
from django.contrib.auth import get_user_model

User = get_user_model()


class Announcement(models.Model):
    AUDIENCE_CHOICES = [
        ("all", "All Active Members"),
        ("officers", "Officers Only"),
        ("guests", "Guests Only"),
    ]

    subject = models.CharField(max_length=200)
    body = models.TextField(help_text="Write your message here.")
    audience = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default="all")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.subject

    def send(self):
        """
        Logic to filter users and send the email.
        """
        if self.audience == "officers":
            recipients = User.objects.filter(is_officer=True, is_active=True)
        elif self.audience == "guests":
            recipients = User.objects.filter(is_guest=True, is_active=True)
        else:
            recipients = User.objects.filter(is_active=True)

        # Prepare messages (Mass Mail is more efficient)
        messages = []
        sender = settings.EMAIL_HOST_USER

        for user in recipients:
            if user.email:
                messages.append(
                    (
                        self.subject,
                        self.body,
                        sender,
                        [user.email],
                    )
                )

        # Send
        count = send_mass_mail(tuple(messages), fail_silently=False)
        return count
