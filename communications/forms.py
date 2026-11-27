import json

from django import forms

from core.widgets import EmojiTextarea, EmojiTextInput

from .models import Announcement, EmailTemplate


class TemplatePicker(forms.Select):
    """A select that carries every template's text, so ``template-picker.js``
    can fill in the subject and body without reloading the page (which would
    lose the audience and recipient selections)."""

    class Media:
        js = ("communications/template-picker.js",)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["attrs"]["data-email-templates"] = json.dumps({
            str(t.pk): {"subject": t.subject, "body": t.body}
            for t in EmailTemplate.objects.all()
        })
        return context


class EmailTemplateAdminForm(forms.ModelForm):
    class Meta:
        model = EmailTemplate
        fields = "__all__"
        widgets = {
            "subject": EmojiTextInput,
            "body": EmojiTextarea,
        }


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

    # Not stored: picking one only copies its text into the fields below.
    template = forms.ModelChoiceField(
        queryset=EmailTemplate.objects.all(),
        required=False,
        label="Start from template",
        widget=TemplatePicker,
        help_text="Copies the template’s subject and body into the fields "
        "below, where you can edit them.",
    )

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
