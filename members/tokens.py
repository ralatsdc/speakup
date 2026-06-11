"""Signed, time-limited tokens for emailed links.

Both flows put a short-lived signed token in a URL emailed to the user:

* **magic-link login** — payload is the user's pk; the link signs them in.
* **email change** — payload is the user's pk plus the *new* address; the link
  is sent to the new address and confirms the change.

Tokens are stateless (no DB row) and tamper-proof via ``django.core.signing``.
Expiry is enforced by ``max_age`` at read time. A magic-link token is also bound
to the user's current password hash, so changing the password invalidates any
outstanding links.
"""

from django.contrib.auth import get_user_model
from django.core import signing

User = get_user_model()

_LOGIN_SALT = "members.magic-link"
_EMAIL_SALT = "members.email-change"


def _password_fingerprint(user):
    """A short, stable fingerprint of the password hash. Including it in the
    login token means a password change (or reset) invalidates outstanding
    magic links."""
    return (user.password or "")[-16:]


# --- magic-link login ------------------------------------------------------

def make_login_token(user):
    return signing.dumps(
        {"pk": user.pk, "pw": _password_fingerprint(user)}, salt=_LOGIN_SALT
    )


def read_login_token(token, max_age):
    """Return the ``User`` for a valid, unexpired login token, else ``None``."""
    try:
        data = signing.loads(token, salt=_LOGIN_SALT, max_age=max_age)
    except (signing.BadSignature, signing.SignatureExpired):
        return None
    user = User.objects.filter(pk=data.get("pk")).first()
    if user is None or data.get("pw") != _password_fingerprint(user):
        return None
    return user


# --- email change ----------------------------------------------------------

def make_email_change_token(user, new_email):
    return signing.dumps(
        {"pk": user.pk, "email": new_email}, salt=_EMAIL_SALT
    )


def read_email_change_token(token, max_age):
    """Return ``(user, new_email)`` for a valid, unexpired token, else
    ``(None, None)``."""
    try:
        data = signing.loads(token, salt=_EMAIL_SALT, max_age=max_age)
    except (signing.BadSignature, signing.SignatureExpired):
        return None, None
    user = User.objects.filter(pk=data.get("pk")).first()
    if user is None:
        return None, None
    return user, data.get("email")
