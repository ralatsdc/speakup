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


@admin.action(description="Make Guest")
def make_guest(modeladmin, request, queryset):
    count = queryset.update(is_guest=True)
    modeladmin.message_user(request, f"{count} user(s) marked as guest.")


@admin.action(description="Remove Guest")
def remove_guest(modeladmin, request, queryset):
    count = queryset.update(is_guest=False)
    modeladmin.message_user(request, f"{count} user(s) unmarked as guest.")


@admin.action(description="Make Officer")
def make_officer(modeladmin, request, queryset):
    count = queryset.update(is_officer=True)
    modeladmin.message_user(request, f"{count} user(s) marked as officer.")


@admin.action(description="Remove Officer")
def remove_officer(modeladmin, request, queryset):
    count = queryset.update(is_officer=False)
    modeladmin.message_user(request, f"{count} user(s) unmarked as officer.")


# TODO: Restore?
# @admin.action(description="Make Staff")
# def make_staff(modeladmin, request, queryset):
#     count = queryset.update(is_staff=True)
#     modeladmin.message_user(request, f"{count} user(s) marked as staff.")


# TODO: Restore?
# @admin.action(description="Remove Staff")
# def remove_staff(modeladmin, request, queryset):
#     count = queryset.update(is_staff=False)
#     modeladmin.message_user(request, f"{count} user(s) unmarked as staff.")


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
        "is_active",
        "email",
    )

    # Filters on the right sidebar (Find guests quickly!)
    list_filter = ("is_guest", "is_officer", "is_active")

    # Search bar capability
    search_fields = ("username", "first_name", "last_name", "email")

    # TODO: Restore?
    # actions = [make_guest, remove_guest, make_officer, remove_officer, make_staff, remove_staff]
    actions = [make_guest, remove_guest, make_officer, remove_officer]



# admin.site.unregister(User) # Unregister the default if needed, though we didn't use the default
admin.site.register(User, CustomUserAdmin)
