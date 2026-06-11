"""Authentication backend that lets members sign in with their email.

``members.User`` keeps ``username`` as its ``USERNAME_FIELD`` (a Django
requirement inherited from ``AbstractUser``), but usernames are auto-generated
and never shown to members — they identify themselves by email, which is unique
and lowercased on save. This backend treats the value the login form submits as
``username`` as an *email* and looks the user up that way.

It is registered ahead of Django's default ``ModelBackend`` (see
``AUTHENTICATION_BACKENDS``). When the submitted value isn't a known email this
backend returns ``None`` and the chain falls through to ``ModelBackend``, so the
Django admin's username login still works for superusers.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()


class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        # The auth form / ``authenticate()`` may pass the identifier either as
        # ``username`` (Django's convention) or under the model's USERNAME_FIELD.
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if username is None or password is None:
            return None

        try:
            user = User.objects.get(email__iexact=username.strip())
        except User.DoesNotExist:
            # Run the default hasher once to keep timing comparable to the
            # success path, mitigating user-enumeration via response time.
            User().set_password(password)
            return None
        except User.MultipleObjectsReturned:
            # Shouldn't happen (email is unique post-normalization), but never
            # authenticate ambiguously.
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
