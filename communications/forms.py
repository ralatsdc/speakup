from django import forms

from core.widgets import EmojiTextarea, EmojiTextInput

from .emails import allowed_senders
from .models import Announcement


class AnnouncementAdminForm(forms.ModelForm):
    """Keeps audience and hand-picked recipients consistent.

    The two are alternatives, so each half-configured combination is an error
    rather than something we quietly resolve: silently mailing nobody, or
    silently dropping the names an officer just picked, are both worse than
    saying so at save time.

    This lives on the form rather than in ``Model.clean`` because a
    many-to-many isn't readable until the row exists — on an add form the
    picked recipients are only available here, in ``cleaned_data``.
    """

    class Meta:
        model = Announcement
        fields = "__all__"
        # Announcements are the one place officers write prose that members
        # read as-is, and emoji are part of that voice. The OS picker is the
        # only alternative and it is both undiscoverable and awkward mid-line.
        widgets = {
            "subject": EmojiTextInput,
            "body": EmojiTextarea,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Choices come from settings at request time so the list can change
        # (a newly verified sender) without a migration. A saved value that has
        # since left the list stays selectable so editing doesn't silently
        # reset it; sending it is refused by emails.resolve_sender.
        senders = allowed_senders()
        current = self.instance.from_email if self.instance else ""
        if current and current not in senders:
            senders.append(current)
        self.fields["from_email"] = forms.ChoiceField(
            label="Send from",
            required=False,
            choices=[("", f"Default ({senders[0]})")] + [(s, s) for s in senders],
            help_text=self.fields["from_email"].help_text,
        )

    def clean(self):
        cleaned = super().clean()
        audience = cleaned.get("audience")
        recipients = cleaned.get("recipients")

        if audience == Announcement.AUDIENCE_SELECTED:
            if not recipients:
                self.add_error(
                    "recipients",
                    "Pick at least one member, or choose a different audience.",
                )
        elif recipients:
            self.add_error(
                "recipients",
                "Selected members are only sent to when the audience is "
                "“Selected Members”. Either switch the audience or clear this "
                "selection.",
            )
        return cleaned
