from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm
from import_export.admin import ImportExportModelAdmin
from .models import User
from .resources import UserResource

DEFAULT_PASSWORD = "Speak-Up-2026"


class CustomUserCreationForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["password1"] = DEFAULT_PASSWORD
        self.initial["password2"] = DEFAULT_PASSWORD
        self.fields["password1"].widget.render_value = True
        self.fields["password2"].widget.render_value = True


class CustomUserAdmin(ImportExportModelAdmin, UserAdmin):
    add_form = CustomUserCreationForm
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
            },
        ),
    )
    resource_class = UserResource # Link the logic we just wrote
    # Add your custom fields to the 'fieldsets' so you can edit them
    fieldsets = UserAdmin.fieldsets + (
        (
            "Toastmasters Profile",
            {
                "fields": (
                    "is_guest",
                    "join_date",
                    "notes",
                    "phone_number",
                    "is_officer",
                    "mentor",
                )
            },
        ),
    )

    # Columns to show in the list view
    list_display = (
        "username",
        "first_name",
        "last_name",
        "is_guest",
        "is_officer",
        "email",
    )

    # Filters on the right sidebar (Find guests quickly!)
    list_filter = ("is_guest", "is_officer", "is_active")

    # Search bar capability
    search_fields = ("username", "first_name", "last_name", "email")


# admin.site.unregister(User) # Unregister the default if needed, though we didn't use the default
admin.site.register(User, CustomUserAdmin)
