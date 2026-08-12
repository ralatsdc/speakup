from django import forms

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
