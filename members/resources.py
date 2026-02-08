from import_export import resources, fields
from import_export.widgets import BooleanWidget
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.utils.crypto import get_random_string

User = get_user_model()


class UserResource(resources.ModelResource):
    # We can explicitly define fields if we want specific column headers
    # checking 'is_guest' allows you to bulk upload guests vs members
    is_guest = fields.Field(
        attribute="is_guest", column_name="is_guest", widget=BooleanWidget()
    )

    class Meta:
        model = User
        # The field used to identify if a user already exists (updates vs creates)
        import_id_fields = ("username",)

        # The fields to expose in the CSV
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "is_guest",
            "join_date",
        )

        # Exclude sensitive or internal fields
        exclude = ("password", "is_superuser", "is_staff", "groups", "user_permissions")

    def before_import_row(self, row, **kwargs):
        """
        Logic to run BEFORE the data hits the internal instance loader.
        Useful for generating usernames if they are missing.
        """
        # If CSV has no username but has email, generate username from email
        if "email" in row and not row.get("username"):
            row["username"] = row["email"].split("@")[0]

        # Ensure is_guest defaults to True if missing
        if "is_guest" not in row:
            row["is_guest"] = "1"  # '1' is True in BooleanWidget

    def before_save_instance(self, instance, row, **kwargs):
        """
        Logic to run right before saving the user.
        Handle Passwords here.
        """
        # If this is a new user and they don't have a password set
        if not instance.pk and not instance.password:
            # Set a default password
            instance.password = make_password("SpeakUp2025!")

        # If you included a 'password' column in your CSV (plain text), hash it here:
        # elif instance.password and not instance.password.startswith('pbkdf2_'):
        #     instance.password = make_password(instance.password)
