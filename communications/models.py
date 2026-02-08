from django.db import models

from .utils import send_announcement


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
        return send_announcement(self)
