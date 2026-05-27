from django.apps import AppConfig


class MembersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "members"

    def ready(self):
        # Wire the is_officer ↔ is_staff + Officers-group sync signal.
        from . import signals  # noqa: F401
