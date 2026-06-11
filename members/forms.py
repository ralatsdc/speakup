"""Member-facing forms: email login, profile editing, email change.

Auth uses email as the identifier (see ``members.auth.EmailBackend``), so the
login form relabels Django's ``username`` field as "Email"."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm


class EmailAuthenticationForm(AuthenticationForm):
    """Login form that presents the identifier as an email address. The field
    is still named ``username`` (what ``AuthenticationForm``/``LoginView``
    expect); ``EmailBackend`` interprets the submitted value as an email."""

    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs={"autofocus": True, "autocomplete": "email", "class": "form-control"}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password"].widget.attrs.update({"class": "form-control"})
