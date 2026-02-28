from import_export import resources, fields
from import_export.widgets import BooleanWidget
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.utils.crypto import get_random_string

User = get_user_model()


class UserResource(resources.ModelResource):
    """Handles CSV import/export of User records via django-import-export."""

    is_guest = fields.Field(
        attribute="is_guest", column_name="is_guest", widget=BooleanWidget()
    )
    is_officer = fields.Field(
        attribute="is_officer", column_name="is_officer", widget=BooleanWidget()
    )
    is_staff = fields.Field(
        attribute="is_staff", column_name="is_staff", widget=BooleanWidget()
    )

    class Meta:
        model = User
        import_id_fields = ("username",)
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "is_guest",
            "is_officer",
            "is_staff",
            "join_date",
        )
        exclude = ("password", "is_superuser", "groups", "user_permissions")

    def before_import_row(self, row, **kwargs):
        """Auto-generate username from email and default is_guest to True."""
        if "email" in row and not row.get("username"):
            row["username"] = row["email"].split("@")[0]

        if not row.get("is_guest"):
            row["is_guest"] = "1"

        if not row.get("is_officer"):
            row["is_officer"] = "0"

        if not row.get("is_staff"):
            row["is_staff"] = "0"

    def before_save_instance(self, instance, row, **kwargs):
        """Assign a random password to newly imported users."""
        if not instance.pk and not instance.password:
            instance.password = make_password(get_random_string(12))
