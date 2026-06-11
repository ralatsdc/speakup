"""Self-service account page: edit name, set/change password, change email.

One page (``account``) renders three independent forms, each posting to its own
view. On success a view adds a flash message and redirects back to the page; on
error it re-renders the page with that form's errors, leaving the others fresh.

Email changes are confirmed out-of-band: the new address only takes effect once
the member clicks a link sent *to* it (``account_email_confirm``), so a typo or
someone else's address can't lock them out.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .emails import send_email_change_confirmation
from .forms import EmailChangeForm, ProfileForm, SetPasswordForm
from .tokens import read_email_change_token

User = get_user_model()


def _render_account(request, *, profile_form=None, password_form=None, email_form=None):
    # The member is already authenticated here, so password setting doesn't
    # require the current password (SetPasswordForm). This matters because most
    # members reach this page via a magic link and were issued a random password
    # at account creation that they've never known.
    user = request.user
    context = {
        "profile_form": profile_form or ProfileForm(instance=user),
        "password_form": password_form or SetPasswordForm(user),
        "email_form": email_form or EmailChangeForm(user),
    }
    return render(request, "members/account.html", context)


@login_required
def account(request):
    return _render_account(request)


@login_required
@require_http_methods(["POST"])
def account_profile(request):
    form = ProfileForm(request.POST, instance=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, "Your name has been updated.")
        return redirect("account")
    return _render_account(request, profile_form=form)


@login_required
@require_http_methods(["POST"])
def account_password(request):
    form = SetPasswordForm(request.user, request.POST)
    if form.is_valid():
        user = form.save()
        # Keep the member signed in after the password hash changes.
        update_session_auth_hash(request, user)
        messages.success(request, "Your password has been saved.")
        return redirect("account")
    return _render_account(request, password_form=form)


@login_required
@require_http_methods(["POST"])
def account_email(request):
    form = EmailChangeForm(request.user, request.POST)
    if form.is_valid():
        new_email = form.cleaned_data["new_email"]
        send_email_change_confirmation(request.user, new_email)
        messages.success(
            request,
            f"We've sent a confirmation link to {new_email}. Your email will "
            f"change once you click it.",
        )
        return redirect("account")
    return _render_account(request, email_form=form)


@login_required
def account_email_confirm(request, token):
    user, new_email = read_email_change_token(token, settings.EMAIL_CHANGE_MAX_AGE)
    # The link must belong to the signed-in member and still be valid.
    if user is None or new_email is None or user.pk != request.user.pk:
        messages.error(request, "That email-change link is invalid or has expired.")
        return redirect("account")

    # Re-check availability in case the address was taken since the link was sent.
    if User.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists():
        messages.error(request, "That email address is now in use; change not applied.")
        return redirect("account")

    user.email = new_email
    user.save()
    messages.success(request, "Your email address has been updated.")
    return redirect("account")
