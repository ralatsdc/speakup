"""Member-facing forms: email login, profile editing, email change.

Auth uses email as the identifier (see ``members.auth.EmailBackend``), so the
login form relabels Django's ``username`` field as "Email"."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    SetPasswordForm as AuthSetPasswordForm,
)

User = get_user_model()


class _BootstrapMixin:
    """Add Bootstrap's ``form-control`` class to every field's widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


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


class ProfileForm(_BootstrapMixin, forms.ModelForm):
    """Self-service editing of the member's own name."""

    class Meta:
        model = User
        fields = ["first_name", "last_name"]


class SetPasswordForm(_BootstrapMixin, AuthSetPasswordForm):
    """Bootstrap-styled "set a new password" form. Used on the account page for
    an already-authenticated member, so it never asks for the current password
    (which magic-link members were never given)."""


class EmailChangeForm(forms.Form):
    """Request a change to the member's login email. The new address is only
    applied after it's confirmed via a link sent to it (see account views), so
    this form just validates that the address is new and not already taken."""

    new_email = forms.EmailField(
        label="New email",
        widget=forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_new_email(self):
        email = self.cleaned_data["new_email"].strip().lower()
        if email == (self.user.email or "").lower():
            raise forms.ValidationError("That's already your email address.")
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("That email address is already in use.")
        return email
