from django.conf import settings
from email.utils import formataddr

from django.db import models

from .utils import send_announcement


class Announcement(models.Model):
    AUDIENCE_SELECTED = "selected"
    AUDIENCE_CHOICES = [
        ("all", "All Active Members"),
        ("officers", "Officers Only"),
        ("guests", "Guests Only"),
        (AUDIENCE_SELECTED, "Selected Members"),
    ]

    subject = models.CharField(max_length=200)
    body = models.TextField(
        help_text="Write your message here. Markdown is supported "
        "(**bold**, *italic*, [links](https://…), - lists) along with emojis "
        "and the {first_name} placeholder.")
    audience = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default="all")
    # Only consulted when audience is "selected" — the audiences are
    # alternatives, not a group plus extras. Picking a predefined audience and
    # also naming people would silently drop the names, so the admin form
    # rejects that combination rather than guessing.
    recipients = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="announcements",
        help_text="Used only when the audience is “Selected Members”. Unlike "
        "the predefined audiences, guests can be picked here.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.subject

    def send(self):
        return send_announcement(self)


class Sender(models.Model):
    """An address officers can choose to send club email from.

    The club's default sender is still ``settings.DEFAULT_FROM_EMAIL`` — it is
    always offered and is what automatic mail (sign-in links, welcome, guides)
    uses. Rows here are the *additional* choices on the review-before-send
    page. Each address must be on a domain or sender verified in Brevo; this
    table can't check that, so an unverified one fails at delivery.
    """

    name = models.CharField(
        max_length=100, blank=True,
        help_text="Shown to recipients, e.g. “Speak Up Cambridge — President”.")
    email = models.EmailField(
        unique=True,
        help_text="Must be verified in Brevo (on the authenticated domain), "
        "or messages will fail or land in spam.")
    is_active = models.BooleanField(
        default=True, help_text="Untick to retire a sender without deleting it.")

    class Meta:
        ordering = ["name", "email"]

    def __str__(self):
        return self.header

    @property
    def header(self):
        """The RFC 5322 From value, e.g. ``Name <addr>``."""
        return formataddr((self.name, self.email)) if self.name else self.email
