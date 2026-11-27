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


class AnnouncementDelivery(models.Model):
    """What happened to one recipient during one-at-a-time sending.

    A row means the recipient is handled (sent or skipped). While the
    announcement is unfinished, neither send path will mail them again. The
    normal bulk send doesn't create rows.
    """

    SENT = "sent"
    SKIPPED = "skipped"
    STATUS_CHOICES = [(SENT, "Sent"), (SKIPPED, "Skipped")]

    announcement = models.ForeignKey(
        Announcement, on_delete=models.CASCADE, related_name="deliveries")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+")
    # Copied at the time, so the history survives later changes to the member.
    name = models.CharField(max_length=301)
    email = models.EmailField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    # What was actually sent; blank for a skip.
    sender = models.CharField(max_length=400, blank=True)
    subject = models.TextField(blank=True)
    body = models.TextField(blank=True)
    handled_at = models.DateTimeField(auto_now_add=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["handled_at", "pk"]
        verbose_name_plural = "one-at-a-time deliveries"
        constraints = [
            models.UniqueConstraint(
                fields=["announcement", "user"],
                name="one_delivery_per_recipient"),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_status_display().lower()})"


class EmailTemplate(models.Model):
    """Reusable starting text for an announcement.

    Choosing one *copies* its subject and body into the announcement; no link
    is kept, so editing or deleting a template never changes an announcement.
    """

    name = models.CharField(
        max_length=200, unique=True,
        help_text="How it appears in the “Start from template” list.")
    subject = models.CharField(max_length=200)
    body = models.TextField(
        help_text="Markdown is supported (**bold**, *italic*, "
        "[links](https://…), - lists) along with emojis and the "
        "{first_name} placeholder.")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @classmethod
    def create_from(cls, announcement):
        """Save an announcement's text as a new template, named after its
        subject, with a numeric suffix if that name is taken."""
        max_length = cls._meta.get_field("name").max_length
        name = announcement.subject[:max_length]
        number = 1
        while cls.objects.filter(name=name).exists():
            number += 1
            suffix = f" ({number})"
            name = announcement.subject[:max_length - len(suffix)] + suffix
        return cls.objects.create(
            name=name, subject=announcement.subject, body=announcement.body)


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
